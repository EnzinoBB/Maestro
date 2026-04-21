"""Hub unit tests using in-process FastAPI WebSocket client."""
import asyncio
import json
import uuid

import pytest
from fastapi import FastAPI, Query, WebSocket
from fastapi.testclient import TestClient

from app.ws import Hub
from app.ws.protocol import (
    make_message, T_REQ_STATE_GET, T_RES_STATE_GET, T_PONG,
)


@pytest.fixture
def app_with_hub():
    hub = Hub()
    app = FastAPI()
    app.state.hub = hub

    @app.websocket("/ws/daemon")
    async def ws(ws: WebSocket, host_id: str = Query(...)):
        await hub.handle_daemon_ws(ws, host_id, token=None)

    return app, hub


def test_register_and_request_response(app_with_hub):
    app, hub = app_with_hub
    client = TestClient(app)
    with client.websocket_connect("/ws/daemon?host_id=h1") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"
        # send hello_ack
        ws.send_json({
            "id": "d-1", "type": "hello_ack", "in_reply_to": hello["id"],
            "payload": {"daemon_version": "t", "runners_available": ["docker"]},
        })

        # from the control plane, enqueue a request and simulate daemon reply via this ws
        # We'll run an asyncio task that sends a request from the hub while we,
        # in this sync client, read and respond.
        async def issue_request():
            resp = await hub.request("h1", T_REQ_STATE_GET, {}, timeout=2.0)
            return resp

        loop = asyncio.new_event_loop()
        task = loop.create_task(issue_request())

        # process one tick so the request is written
        async def tick():
            await asyncio.sleep(0.05)
        loop.run_until_complete(tick())

        # read the request from the client side
        req = ws.receive_json()
        assert req["type"] == T_REQ_STATE_GET

        # send reply
        ws.send_json({
            "id": f"dmn-{uuid.uuid4().hex[:6]}", "type": T_RES_STATE_GET,
            "in_reply_to": req["id"],
            "payload": {"components": [{"id": "x", "status": "running", "component_hash": "h"}]},
        })

        resp = loop.run_until_complete(task)
        loop.close()
        assert resp.type == T_RES_STATE_GET
        assert resp.payload["components"][0]["id"] == "x"


def test_list_hosts_reports_connected(app_with_hub):
    app, hub = app_with_hub
    client = TestClient(app)
    with client.websocket_connect("/ws/daemon?host_id=h1") as ws:
        hello = ws.receive_json()
        ws.send_json({
            "id": "d-1", "type": "hello_ack", "in_reply_to": hello["id"],
            "payload": {"daemon_version": "t", "runners_available": ["docker"]},
        })
        # small tick to register
        import time; time.sleep(0.1)
        hosts = hub.list_hosts()
        assert len(hosts) == 1
        assert hosts[0]["host_id"] == "h1"
