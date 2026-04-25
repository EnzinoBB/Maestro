import json
import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.ws.protocol import make_message, T_EV_METRICS


@pytest.fixture
def client(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("MAESTRO_DB", os.path.join(td, "t.db"))
        monkeypatch.setenv("MAESTRO_METRICS_RETENTION_INTERVAL_S", "3600")
        app = create_app()
        with TestClient(app) as c:
            yield c, app


def test_ws_ui_delivers_hello_on_connect(client):
    c, _app = client
    with c.websocket_connect("/ws/ui") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "hello"
        assert isinstance(msg.get("server_version"), str)


@pytest.mark.asyncio
async def test_ws_ui_forwards_hub_metrics_event(client):
    c, app = client
    with c.websocket_connect("/ws/ui") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"

        msg = make_message(T_EV_METRICS, {
            "ts": "2026-04-24T10:00:00Z",
            "samples": [
                {"scope": "host", "scope_id": "h1", "metric": "cpu_percent", "value": 12.5},
            ],
        })
        await app.state.hub._emit("h1", msg)

        frame = ws.receive_json()
        assert frame["type"] == "hub.event"
        assert frame["host_id"] == "h1"
        assert frame["event_type"] == "event.metrics"
        assert frame["summary"]["samples"] == 1


def test_ws_ui_pong_on_ping(client):
    c, _app = client
    with c.websocket_connect("/ws/ui") as ws:
        ws.receive_json()  # hello
        ws.send_text(json.dumps({"type": "ping"}))
        pong = ws.receive_json()
        assert pong["type"] == "pong"
