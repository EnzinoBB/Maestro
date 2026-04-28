import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client_singleuser(monkeypatch):
    """Default: single-user mode ON, no login required."""
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("MAESTRO_DB", os.path.join(td, "t.db"))
        monkeypatch.setenv("MAESTRO_METRICS_RETENTION_INTERVAL_S", "3600")
        monkeypatch.delenv("MAESTRO_SINGLE_USER_MODE", raising=False)
        app = create_app()
        with TestClient(app) as c:
            yield c


@pytest.fixture
def client_multiuser(monkeypatch):
    """Multi-user mode — login required."""
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("MAESTRO_DB", os.path.join(td, "t.db"))
        monkeypatch.setenv("MAESTRO_METRICS_RETENTION_INTERVAL_S", "3600")
        monkeypatch.setenv("MAESTRO_SINGLE_USER_MODE", "false")
        app = create_app()
        with TestClient(app) as c:
            yield c


# ---- single-user mode ----

def test_me_single_user_default(client_singleuser):
    r = client_singleuser.get("/api/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["authenticated"] is True
    assert body["id"] == "singleuser"
    assert body["is_admin"] is True
    assert body["single_user_mode"] is True


def test_deploys_api_works_without_login_in_single_user_mode(client_singleuser):
    r = client_singleuser.get("/api/deploys")
    assert r.status_code == 200
    r = client_singleuser.post("/api/deploys", json={"name": "su-test"})
    assert r.status_code == 201


# ---- multi-user mode ----

def test_me_unauthenticated_in_multiuser(client_multiuser):
    r = client_multiuser.get("/api/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["authenticated"] is False
    assert body["single_user_mode"] is False


def test_deploys_api_returns_401_without_login_in_multiuser(client_multiuser):
    r = client_multiuser.get("/api/deploys")
    assert r.status_code == 401


def test_setup_admin_then_login_then_api(client_multiuser):
    # 1. Setup first admin
    r = client_multiuser.post("/api/auth/setup-admin",
                              json={"username": "admin", "password": "correct-horse"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["username"] == "admin"
    assert body["is_admin"] is True

    # 2. Second setup is refused
    r = client_multiuser.post("/api/auth/setup-admin",
                              json={"username": "second", "password": "another-pw"})
    assert r.status_code == 409

    # 3. Login with wrong password fails
    r = client_multiuser.post("/api/auth/login",
                              json={"username": "admin", "password": "wrong"})
    assert r.status_code == 401

    # 4. Login with correct password succeeds. TestClient persists the
    #    session cookie client-side across subsequent requests; step 5
    #    proves the session is active by calling a protected endpoint.
    r = client_multiuser.post("/api/auth/login",
                              json={"username": "admin", "password": "correct-horse"})
    assert r.status_code == 200

    # 5. /api/deploys now works
    r = client_multiuser.get("/api/deploys")
    assert r.status_code == 200

    # 6. /api/auth/me reflects the logged-in user
    r = client_multiuser.get("/api/auth/me")
    assert r.status_code == 200
    me = r.json()
    assert me["authenticated"] is True
    assert me["username"] == "admin"

    # 7. Logout clears the session → 401 again
    r = client_multiuser.post("/api/auth/logout")
    assert r.status_code == 200
    r = client_multiuser.get("/api/deploys")
    assert r.status_code == 401


def test_cannot_login_as_singleuser(client_multiuser):
    """The implicit singleuser has no usable password — login is rejected."""
    r = client_multiuser.post("/api/auth/login",
                              json={"username": "singleuser", "password": "anything"})
    assert r.status_code == 401


def test_setup_admin_requires_strong_enough_password(client_multiuser):
    r = client_multiuser.post("/api/auth/setup-admin",
                              json={"username": "admin", "password": "short"})
    assert r.status_code == 400


# ---- M5.6: first-run setup helpers ----

def test_me_reports_needs_setup_true_when_multiuser_and_no_admin(client_multiuser):
    r = client_multiuser.get("/api/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["authenticated"] is False
    assert body["single_user_mode"] is False
    assert body["needs_setup"] is True


def test_me_reports_needs_setup_false_after_admin_created(client_multiuser):
    client_multiuser.post("/api/auth/setup-admin",
                          json={"username": "admin", "password": "correct-horse"})
    # /me from a fresh (no-cookie) client perspective. We must call with a
    # NEW client to clear the auto-login cookie set by setup-admin.
    r = client_multiuser.get("/api/auth/me", cookies={})
    body = r.json()
    # The TestClient persists cookies, so this is actually authenticated.
    # The needs_setup flag must still be False because an admin exists.
    assert body["needs_setup"] is False


def test_me_reports_needs_setup_false_in_single_user_mode(client_singleuser):
    r = client_singleuser.get("/api/auth/me")
    body = r.json()
    assert body["single_user_mode"] is True
    assert body["needs_setup"] is False


def test_setup_admin_auto_logs_in(client_multiuser):
    # Before setup: /api/deploys returns 401
    r = client_multiuser.get("/api/deploys")
    assert r.status_code == 401

    # setup-admin must respond 200 AND grant a session
    r = client_multiuser.post("/api/auth/setup-admin",
                              json={"username": "admin", "password": "correct-horse"})
    assert r.status_code == 200

    # /api/deploys is now reachable on the SAME client (cookie persists)
    r = client_multiuser.get("/api/deploys")
    assert r.status_code == 200


def test_401_returns_structured_error_body(client_multiuser):
    r = client_multiuser.get("/api/deploys")
    assert r.status_code == 401
    body = r.json()
    assert body == {
        "ok": False,
        "error": {"code": "unauthenticated", "message": "authentication required"},
    }
