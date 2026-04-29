import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(monkeypatch):
    """Multi-user mode test client (auth required)."""
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("MAESTRO_DB", os.path.join(td, "t.db"))
        monkeypatch.setenv("MAESTRO_METRICS_RETENTION_INTERVAL_S", "3600")
        monkeypatch.setenv("MAESTRO_SESSION_SECRET", "test-secret")
        app = create_app()
        with TestClient(app) as c:
            yield c, app


def test_nodes_requires_auth_in_multiuser(client):
    c, _app = client
    r = c.get("/api/nodes")
    assert r.status_code == 401


def test_admin_users_requires_auth(client):
    c, _app = client
    # Without auth → 401
    r = c.get("/api/admin/users")
    assert r.status_code == 401

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
    body = r.json()
    assert "users" in body
    # At minimum, the created admin should be present
    assert any(u["id"] == "admin" or u["username"] == "admin" for u in body["users"])


def test_orgs_create_admin_only(client):
    c, _app = client
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
