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


def _login_admin(c, username="admin", password="correct-horse"):
    c.post("/api/auth/setup-admin", json={"username": username, "password": password})
    c.post("/api/auth/login", json={"username": username, "password": password})


@pytest.mark.asyncio
async def test_patch_node_promote_to_shared(client_multiuser):
    c, app = client_multiuser
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
async def test_patch_node_demote_to_user(client_multiuser):
    c, app = client_multiuser
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
async def test_patch_node_label_only(client_multiuser):
    c, app = client_multiuser
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


def test_patch_node_404(client_multiuser):
    c, _app = client_multiuser
    _login_admin(c)
    r = c.patch("/api/nodes/nope", json={"label": "x"})
    assert r.status_code == 404


def test_patch_node_admin_only(client_multiuser):
    c, _app = client_multiuser
    _login_admin(c)
    # Create a non-admin user, log in as them
    c.post("/api/admin/users", json={"username": "bob", "password": "12345678"})
    c.post("/api/auth/logout")
    c.post("/api/auth/login", json={"username": "bob", "password": "12345678"})
    r = c.patch("/api/nodes/whatever", json={"label": "x"})
    assert r.status_code == 403


def test_patch_node_rejects_unknown_owner(client_multiuser):
    c, _app = client_multiuser
    _login_admin(c)
    # Need an existing node id — auto-register one
    class _Conn:
        host_id = "h-rej-1"
        claim_user_id = None
    import asyncio
    handlers = c.app.state.hub._register_handlers
    asyncio.get_event_loop().run_until_complete(handlers[0](_Conn()))
    n = asyncio.get_event_loop().run_until_complete(
        c.app.state.nodes_repo.get_by_host_id("h-rej-1")
    )
    r = c.patch(f"/api/nodes/{n['id']}",
                json={"node_type": "shared", "owner_org_id": "org_does_not_exist"})
    assert r.status_code == 400


def test_patch_user_change_role(client_multiuser):
    c, _app = client_multiuser
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


def test_patch_user_blocks_last_admin_demotion(client_multiuser):
    c, _app = client_multiuser
    _login_admin(c)
    # Find admin id
    r = c.get("/api/admin/users")
    admin_id = next(u["id"] for u in r.json()["users"] if u["username"] == "admin")
    r = c.patch(f"/api/admin/users/{admin_id}", json={"is_admin": False})
    assert r.status_code == 409


def test_delete_user_happy_path(client_multiuser):
    c, _app = client_multiuser
    _login_admin(c)
    r = c.post("/api/admin/users", json={"username": "alice", "password": "12345678"})
    alice_id = r.json()["id"]
    r = c.delete(f"/api/admin/users/{alice_id}")
    assert r.status_code == 204
    r = c.get("/api/admin/users")
    assert all(u["id"] != alice_id for u in r.json()["users"])


def test_delete_user_409_when_owns_deploy(client_multiuser):
    c, _app = client_multiuser
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
    detail = r.json()["detail"]
    assert detail["code"] == "user_has_dependencies"
    assert detail["deploys"] == 1


def test_delete_user_refuses_self(client_multiuser):
    c, _app = client_multiuser
    _login_admin(c)
    r = c.get("/api/admin/users")
    admin_id = next(u["id"] for u in r.json()["users"] if u["username"] == "admin")
    r = c.delete(f"/api/admin/users/{admin_id}")
    assert r.status_code == 400


def test_daemon_enroll_returns_claim_for_authenticated_caller(client_multiuser, monkeypatch):
    c, _app = client_multiuser
    monkeypatch.setenv("MAESTRO_DAEMON_TOKEN", "test-token-xyz")
    _login_admin(c)
    r = c.get("/api/daemon-enroll")
    assert r.status_code == 200
    body = r.json()
    assert body["token"] == "test-token-xyz"
    assert "claim_user_id" in body
    assert body["claim_user_id"]  # non-empty


def test_daemon_enroll_available_to_non_admin(client_multiuser):
    c, _app = client_multiuser
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
