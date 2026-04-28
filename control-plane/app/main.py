"""FastAPI application entry point."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, PlainTextResponse

import asyncio

from .ws import Hub
from .orchestrator import Engine
from .storage import Storage
from .storage_deploys import DeployRepository
from .storage_metrics import MetricsRepository
from .metrics.handler import make_metrics_event_handler
from .metrics.retention import retention_loop
from .ws.ui_bus import UIEventBus
from .api.router import router as api_router
from .api.ui import router as ui_router
from .api.install import router as install_router
from .api.deploys import router as deploys_router
from .api.metrics import router as metrics_router
from .api.wizard import router as wizard_router
from .api.auth import router as auth_router
from .api.nodes import router as nodes_router
from .api._errors import install_error_handlers
from .auth.users_repo import UsersRepository
from .auth.middleware import CurrentUserMiddleware, SINGLEUSER_ID
from .storage_nodes import NodesRepository, OrganizationsRepository
from starlette.middleware.sessions import SessionMiddleware


logging.basicConfig(
    level=os.environ.get("MAESTRO_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("maestro.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = os.environ.get("MAESTRO_DB", "control-plane.db")
    storage = Storage(db_path)
    await storage.init()
    hub = Hub()
    engine = Engine(hub)
    metrics_repo = MetricsRepository(db_path)

    # Persist incoming event.metrics into the metrics store.
    hub.add_event_handler(make_metrics_event_handler(metrics_repo))

    # Fan out Hub events to browser WS clients.
    ui_bus = UIEventBus()
    hub.add_event_handler(ui_bus.as_hub_handler())

    app.state.storage = storage
    app.state.deploy_repo = DeployRepository(db_path)
    app.state.metrics_repo = metrics_repo
    app.state.users_repo = UsersRepository(db_path)
    app.state.nodes_repo = NodesRepository(db_path)
    app.state.orgs_repo = OrganizationsRepository(db_path)
    app.state.hub = hub
    app.state.engine = engine
    app.state.ui_bus = ui_bus

    # Auto-register a node row when a daemon connects, so admins/users can
    # claim/share it. In single-user mode we attribute to 'singleuser';
    # in multi-user mode we attribute to the first admin we can find. If no
    # admin exists yet (fresh install) we skip and the daemon will be
    # claimable from the admin UI later.
    async def _auto_register_node(conn) -> None:
        nodes = app.state.nodes_repo
        existing = await nodes.get_by_host_id(conn.host_id)
        if existing is not None:
            return
        # Resolve owner
        owner = SINGLEUSER_ID
        # In multi-user mode the singleuser still exists but is dormant.
        # If a real admin exists, use them; otherwise fall back to singleuser.
        async with __import__("aiosqlite").connect(db_path) as _db:
            async with _db.execute(
                "SELECT id FROM users WHERE is_admin=1 AND id != 'singleuser' "
                "ORDER BY created_at ASC LIMIT 1"
            ) as cur:
                row = await cur.fetchone()
                if row:
                    owner = row[0]
        await nodes.upsert_user_node(host_id=conn.host_id, owner_user_id=owner)
    hub.add_register_handler(_auto_register_node)

    interval = int(os.environ.get("MAESTRO_METRICS_RETENTION_INTERVAL_S", "600"))
    retention_task = asyncio.create_task(retention_loop(
        metrics_repo, interval_seconds=interval,
    ))

    log.info("control plane ready (db=%s, retention every %ss)", db_path, interval)
    try:
        yield
    finally:
        retention_task.cancel()
        try:
            await retention_task
        except asyncio.CancelledError:
            pass
        log.info("control plane shutting down")


def create_app() -> FastAPI:
    app = FastAPI(title="Maestro Control Plane", version="0.1.0", lifespan=lifespan)

    install_error_handlers(app)

    # Starlette middleware: last add_middleware becomes outermost (runs first
    # on request). We want SessionMiddleware to parse the cookie BEFORE
    # CurrentUserMiddleware reads the session, so CurrentUserMiddleware is
    # added FIRST (innermost) and SessionMiddleware LAST (outermost).
    app.add_middleware(CurrentUserMiddleware)

    secret = os.environ.get("MAESTRO_SESSION_SECRET") or os.urandom(32).hex()
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret,
        session_cookie="maestro_session",
        https_only=False,  # dev; flip to True behind TLS
        same_site="lax",
        max_age=7 * 24 * 3600,
    )

    app.include_router(api_router)
    app.include_router(deploys_router)
    app.include_router(metrics_router)
    app.include_router(wizard_router)
    app.include_router(auth_router)
    app.include_router(nodes_router)
    app.include_router(ui_router)
    app.include_router(install_router)

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    @app.websocket("/ws/daemon")
    async def ws_daemon(
        ws: WebSocket,
        host_id: str = Query(...),
        token: str = Query(""),
    ):
        expected = os.environ.get("MAESTRO_DAEMON_TOKEN") or None
        await app.state.hub.handle_daemon_ws(
            ws, host_id=host_id, token=token or None,
            expected_token=expected,
        )

    @app.websocket("/ws/ui")
    async def ws_ui(ws: WebSocket):
        import json as _json
        await ws.accept()

        await ws.send_text(_json.dumps({
            "type": "hello",
            "server_version": app.version,
        }))

        queue: asyncio.Queue = asyncio.Queue(maxsize=256)

        def _on_frame(frame: dict) -> None:
            try:
                queue.put_nowait(frame)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.put_nowait(frame)
                except Exception:
                    pass

        unsub = app.state.ui_bus.subscribe(_on_frame)

        async def sender():
            while True:
                frame = await queue.get()
                await ws.send_text(_json.dumps(frame))

        send_task = asyncio.create_task(sender())
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    data = _json.loads(raw)
                except Exception:
                    continue
                if data.get("type") == "ping":
                    await ws.send_text(_json.dumps({"type": "pong"}))
        except Exception:
            pass
        finally:
            unsub()
            send_task.cancel()

    # Static web: prefer the new SPA bundle (web-ui/dist) when present;
    # fall back to the legacy HTMX dashboard (control-plane/web) during transition.
    #
    # We probe two candidate locations because the layout differs between dev
    # and the docker image:
    #   dev    : repo_root/web-ui/dist     (sibling of control-plane/)
    #   docker : /app/web-ui/dist          (Dockerfile COPYs the build there;
    #            equivalent to here/"web-ui"/"dist" since here == /app)
    here = Path(__file__).parent.parent           # control-plane/ in dev, /app in docker
    repo_root = here.parent                       # repo root in dev,    /     in docker
    spa_candidates = [
        here / "web-ui" / "dist",                 # docker layout
        repo_root / "web-ui" / "dist",            # dev layout
    ]
    new_ui = next((p for p in spa_candidates if p.is_dir()), spa_candidates[-1])
    legacy_web = here / "web"

    if new_ui.is_dir():
        # Mount hashed assets under /assets; serve index.html for everything
        # else so the SPA can own client-side routing.
        assets_dir = new_ui / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="spa-assets")
        idx = new_ui / "index.html"

        @app.get("/")
        async def spa_root():
            return FileResponse(str(idx))

        # Catch-all for client-side routes like /deploys/dep_xxx.
        # IMPORTANT: registered last so API/WS/healthz routes take precedence.
        @app.get("/{full_path:path}")
        async def spa_catchall(full_path: str):
            # Don't shadow API, WS, installer, or static-asset routes.
            # Those are resolved by their specific routers; if they reach here,
            # it means the sub-path does not exist — reply 404 rather than
            # tricking the client with an HTML page.
            RESERVED = ("api/", "ws/", "healthz", "ui/", "assets/", "dist/", "install-daemon.sh")
            if full_path.startswith(RESERVED) or full_path == "install-daemon.sh":
                return PlainTextResponse("not found", status_code=404)
            return FileResponse(str(idx))
    elif legacy_web.is_dir():
        app.mount("/static", StaticFiles(directory=str(legacy_web)), name="static")

        @app.get("/")
        async def index():
            idx = legacy_web / "index.html"
            if idx.is_file():
                return FileResponse(str(idx))
            return PlainTextResponse("Maestro control plane — web UI missing")

    return app


app = create_app()
