"""FastAPI application entry point."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, PlainTextResponse

from .ws import Hub
from .orchestrator import Engine
from .storage import Storage
from .storage_deploys import DeployRepository
from .api.router import router as api_router
from .api.ui import router as ui_router
from .api.install import router as install_router
from .api.deploys import router as deploys_router


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
    app.state.storage = storage
    app.state.deploy_repo = DeployRepository(db_path)
    app.state.hub = hub
    app.state.engine = engine
    log.info("control plane ready (db=%s)", db_path)
    yield
    log.info("control plane shutting down")


def create_app() -> FastAPI:
    app = FastAPI(title="Maestro Control Plane", version="0.1.0", lifespan=lifespan)
    app.include_router(api_router)
    app.include_router(deploys_router)
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

    # Static web: prefer the new SPA bundle (web-ui/dist) when present;
    # fall back to the legacy HTMX dashboard (control-plane/web) during transition.
    here = Path(__file__).parent.parent           # control-plane/
    repo_root = here.parent                       # repo root
    new_ui = repo_root / "web-ui" / "dist"
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
