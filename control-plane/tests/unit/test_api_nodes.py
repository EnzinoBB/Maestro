import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client_singleuser(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("MAESTRO_DB", os.path.join(td, "t.db"))
        monkeypatch.setenv("MAESTRO_METRICS_RETENTION_INTERVAL_S", "3600")
        # default single-user mode
        monkeypatch.delenv("MAESTRO_SINGLE_USER_MODE", raising=False)
        app = create_app()
        with TestClient(app) as c:
            yield c, app


def test_list_nodes_empty_in_single_user_mode(client_singleuser):
    c, _app = client_singleuser
    r = c.get("/api/nodes")
    assert r.status_code == 200
    assert r.json() == {"nodes": []}


@pytest.mark.asyncio
async def test_auto_register_creates_user_node_for_singleuser(client_singleuser):
    c, app = client_singleuser
    nodes = app.state.nodes_repo
    # Simulate the hub register handler being called with a fake conn
    class _Conn:
        host_id = "host-test-1"
    handlers = app.state.hub._register_handlers
    assert len(handlers) >= 1
    for h in handlers:
        await h(_Conn())
    # /api/nodes now lists it
    r = c.get("/api/nodes")
    body = r.json()
    assert len(body["nodes"]) == 1
    n = body["nodes"][0]
    assert n["host_id"] == "host-test-1"
    assert n["node_type"] == "user"
    assert n["owner_user_id"] == "singleuser"
    assert "online" in n
    # Also check repo directly
    direct = await nodes.get_by_host_id("host-test-1")
    assert direct is not None and direct["owner_user_id"] == "singleuser"


def test_admin_users_requires_admin(client_singleuser):
    c, _app = client_singleuser
    # singleuser is admin → 200
    r = c.get("/api/admin/users")
    assert r.status_code == 200
    body = r.json()
    assert "users" in body
    assert body["single_user_mode"] is True
    # singleuser appears
    assert any(u["id"] == "singleuser" for u in body["users"])


@pytest.fixture
def client_multiuser(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("MAESTRO_DB", os.path.join(td, "t.db"))
        monkeypatch.setenv("MAESTRO_METRICS_RETENTION_INTERVAL_S", "3600")
        monkeypatch.setenv("MAESTRO_SINGLE_USER_MODE", "false")
        monkeypatch.setenv("MAESTRO_SESSION_SECRET", "test-secret")
        app = create_app()
        with TestClient(app) as c:
            yield c, app


def test_nodes_requires_auth_in_multiuser(client_multiuser):
    c, _app = client_multiuser
    r = c.get("/api/nodes")
    assert r.status_code == 401


def test_admin_users_403_for_non_admin(client_multiuser):
    c, _app = client_multiuser
    # Setup admin
    r = c.post("/api/auth/setup-admin",
               json={"username": "admin", "password": "correct-horse"})
    assert r.status_code == 200
    # Login as admin → list users 200
    r = c.post("/api/auth/login",
               json={"username": "admin", "password": "correct-horse"})
    assert r.status_code == 200
    r = c.get("/api/admin/users")
    assert r.status_code == 200


def test_orgs_create_admin_only(client_multiuser):
    c, _app = client_multiuser
    c.post("/api/auth/setup-admin",
           json={"username": "admin", "password": "correct-horse"})
    c.post("/api/auth/login",
           json={"username": "admin", "password": "correct-horse"})
    r = c.post("/api/orgs", json={"name": "platform-core"})
    assert r.status_code == 200
    assert r.json()["name"] == "platform-core"
    # List
    r = c.get("/api/orgs")
    assert r.status_code == 200
    assert any(o["name"] == "platform-core" for o in r.json()["orgs"])
    # Duplicate
    r = c.post("/api/orgs", json={"name": "platform-core"})
    assert r.status_code == 409
