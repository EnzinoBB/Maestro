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
from .api.router import router as api_router
from .api.ui import router as ui_router
from .api.install import router as install_router


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
    app.state.hub = hub
    app.state.engine = engine
    log.info("control plane ready (db=%s)", db_path)
    yield
    log.info("control plane shutting down")


def create_app() -> FastAPI:
    app = FastAPI(title="Maestro Control Plane", version="0.1.0", lifespan=lifespan)
    app.include_router(api_router)
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

    # Static web
    here = Path(__file__).parent.parent
    web_dir = here / "web"
    if web_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(web_dir)), name="static")

        @app.get("/")
        async def index():
            idx = web_dir / "index.html"
            if idx.is_file():
                return FileResponse(str(idx))
            return PlainTextResponse("Maestro control plane — web UI missing")

    return app


app = create_app()
