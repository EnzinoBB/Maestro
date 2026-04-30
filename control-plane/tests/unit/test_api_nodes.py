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


def _login_admin(c, username="admin", password="correct-horse"):
    c.post("/api/auth/setup-admin", json={"username": username, "password": password})
    c.post("/api/auth/login", json={"username": username, "password": password})


@pytest.mark.asyncio
async def test_patch_node_promote_to_shared(client):
    c, app = client
    _login_admin(c)

    # Seed a user node by triggering the auto-register handler
    class _Conn:
        host_id = "h-shared-1"
        claim_user_id = None
    for h in app.state.hub._register_handlers:
        await h(_Conn())
    # Find its id
    n = await app.state.nodes_repo.get_by_host_id("h-shared-1")
    assert n["node_type"] == "user"

    # Create an org to receive the shared node
    r = c.post("/api/orgs", json={"name": "platform"})
    org_id = r.json()["id"]

    r = c.patch(f"/api/nodes/{n['id']}",
                json={"node_type": "shared", "owner_org_id": org_id})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["node_type"] == "shared"
    assert body["owner_user_id"] is None
    assert body["owner_org_id"] == org_id


@pytest.mark.asyncio
async def test_patch_node_demote_to_user(client):
    c, app = client
    _login_admin(c)

    # Create org + shared node
    r = c.post("/api/orgs", json={"name": "platform"})
    org_id = r.json()["id"]
    n = await app.state.nodes_repo.create_shared_node(host_id="h-demote-1", owner_org_id=org_id)
    # Create another user to receive ownership
    r = c.post("/api/admin/users",
               json={"username": "alice", "password": "12345678"})
    alice_id = r.json()["id"]

    r = c.patch(f"/api/nodes/{n['id']}",
                json={"node_type": "user", "owner_user_id": alice_id})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["node_type"] == "user"
    assert body["owner_user_id"] == alice_id
    assert body["owner_org_id"] is None


@pytest.mark.asyncio
async def test_patch_node_label_only(client):
    c, app = client
    _login_admin(c)
    class _Conn:
        host_id = "h-label-1"
        claim_user_id = None
    for h in app.state.hub._register_handlers:
        await h(_Conn())
    n = await app.state.nodes_repo.get_by_host_id("h-label-1")

    r = c.patch(f"/api/nodes/{n['id']}", json={"label": "rack-7"})
    assert r.status_code == 200
    assert r.json()["label"] == "rack-7"

    r = c.patch(f"/api/nodes/{n['id']}", json={"label": None})
    assert r.status_code == 200
    assert r.json()["label"] is None


def test_patch_node_404(client):
    c, _app = client
    _login_admin(c)
    r = c.patch("/api/nodes/nope", json={"label": "x"})
    assert r.status_code == 404


def test_patch_node_admin_only(client):
    c, _app = client
    _login_admin(c)
    # Create a non-admin user, log in as them
    c.post("/api/admin/users", json={"username": "bob", "password": "12345678"})
    c.post("/api/auth/logout")
    c.post("/api/auth/login", json={"username": "bob", "password": "12345678"})
    r = c.patch("/api/nodes/whatever", json={"label": "x"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_patch_node_rejects_unknown_owner(client):
    c, app = client
    _login_admin(c)
    class _Conn:
        host_id = "h-rej-1"
        claim_user_id = None
    for h in app.state.hub._register_handlers:
        await h(_Conn())
    n = await app.state.nodes_repo.get_by_host_id("h-rej-1")
    r = c.patch(f"/api/nodes/{n['id']}",
                json={"node_type": "shared", "owner_org_id": "org_does_not_exist"})
    assert r.status_code == 400


def test_patch_user_change_role(client):
    c, _app = client
    _login_admin(c)
    r = c.post("/api/admin/users", json={"username": "alice", "password": "12345678"})
    alice_id = r.json()["id"]
    assert r.json()["is_admin"] is False

    r = c.patch(f"/api/admin/users/{alice_id}", json={"is_admin": True})
    assert r.status_code == 200
    assert r.json()["is_admin"] is True

    r = c.patch(f"/api/admin/users/{alice_id}", json={"is_admin": False})
    assert r.status_code == 200
    assert r.json()["is_admin"] is False


def test_patch_user_blocks_last_admin_demotion(client):
    c, _app = client
    _login_admin(c)
    # Find admin id
    r = c.get("/api/admin/users")
    admin_id = next(u["id"] for u in r.json()["users"] if u["username"] == "admin")
    r = c.patch(f"/api/admin/users/{admin_id}", json={"is_admin": False})
    assert r.status_code == 409


def test_delete_user_happy_path(client):
    c, _app = client
    _login_admin(c)
    r = c.post("/api/admin/users", json={"username": "alice", "password": "12345678"})
    alice_id = r.json()["id"]
    r = c.delete(f"/api/admin/users/{alice_id}")
    assert r.status_code == 204
    r = c.get("/api/admin/users")
    assert all(u["id"] != alice_id for u in r.json()["users"])


def test_delete_user_409_when_owns_deploy(client):
    c, _app = client
    _login_admin(c)
    # Create alice, log in as alice, create a deploy, log back in as admin, delete
    r = c.post("/api/admin/users", json={"username": "alice", "password": "12345678"})
    alice_id = r.json()["id"]
    c.post("/api/auth/logout")
    c.post("/api/auth/login", json={"username": "alice", "password": "12345678"})
    c.post("/api/deploys", json={"name": "alice-app"})
    c.post("/api/auth/logout")
    c.post("/api/auth/login", json={"username": "admin", "password": "correct-horse"})

    r = c.delete(f"/api/admin/users/{alice_id}")
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "user_has_dependencies"
    assert err["deploys"] == 1


def test_delete_user_refuses_self(client):
    c, _app = client
    _login_admin(c)
    r = c.get("/api/admin/users")
    admin_id = next(u["id"] for u in r.json()["users"] if u["username"] == "admin")
    r = c.delete(f"/api/admin/users/{admin_id}")
    assert r.status_code == 400


def test_daemon_enroll_returns_claim_for_authenticated_caller(client, monkeypatch):
    c, _app = client
    monkeypatch.setenv("MAESTRO_DAEMON_TOKEN", "test-token-xyz")
    _login_admin(c)
    r = c.get("/api/daemon-enroll")
    assert r.status_code == 200
    body = r.json()
    assert body["token"] == "test-token-xyz"
    assert "claim_user_id" in body
    assert body["claim_user_id"]  # non-empty


def test_daemon_enroll_available_to_non_admin(client):
    c, _app = client
    _login_admin(c)
    c.post("/api/admin/users", json={"username": "bob", "password": "12345678"})
    c.post("/api/auth/logout")
    c.post("/api/auth/login", json={"username": "bob", "password": "12345678"})
    r = c.get("/api/daemon-enroll")
    assert r.status_code == 200
    body = r.json()
    # claim_user_id is bob's id, not the admin's
    r2 = c.get("/api/auth/me")
    bob_id = r2.json()["id"]
    assert body["claim_user_id"] == bob_id


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
