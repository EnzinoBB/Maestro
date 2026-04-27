"""Tests for M7 user-management endpoints (admin create user + change password)."""
import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("MAESTRO_DB", os.path.join(td, "t.db"))
        monkeypatch.setenv("MAESTRO_METRICS_RETENTION_INTERVAL_S", "3600")
        monkeypatch.setenv("MAESTRO_SINGLE_USER_MODE", "false")
        app = create_app()
        with TestClient(app) as c:
            # Setup admin so we have a logged-in admin session
            r = c.post("/api/auth/setup-admin",
                       json={"username": "admin", "password": "correct-horse"})
            assert r.status_code == 200, r.text
            yield c


# ---- POST /api/admin/users (create) ----

def test_admin_creates_user(client):
    r = client.post("/api/admin/users", json={
        "username": "alice", "password": "alice-passphrase", "email": "alice@example.com",
        "is_admin": False,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["username"] == "alice"
    assert body["email"] == "alice@example.com"
    assert body["is_admin"] is False
    # User now appears in the list
    r = client.get("/api/admin/users")
    names = [u["username"] for u in r.json()["users"]]
    assert "alice" in names


def test_admin_creates_admin_user(client):
    r = client.post("/api/admin/users", json={
        "username": "boss", "password": "boss-passphrase", "is_admin": True,
    })
    assert r.status_code == 201
    assert r.json()["is_admin"] is True


def test_create_user_requires_strong_password(client):
    r = client.post("/api/admin/users", json={"username": "x", "password": "short"})
    assert r.status_code == 400


def test_create_user_rejects_singleuser_username(client):
    r = client.post("/api/admin/users", json={
        "username": "singleuser", "password": "ten-char-or-more",
    })
    assert r.status_code == 400


def test_create_user_dup_is_409(client):
    client.post("/api/admin/users", json={"username": "alice", "password": "passphrase-1"})
    r = client.post("/api/admin/users", json={"username": "alice", "password": "passphrase-2"})
    assert r.status_code == 409


def test_non_admin_cannot_create_user(client):
    # Create a non-admin user
    r = client.post("/api/admin/users", json={
        "username": "viewer", "password": "viewer-passphrase", "is_admin": False,
    })
    assert r.status_code == 201
    # Logout the admin, login as the viewer, attempt the same call
    client.post("/api/auth/logout")
    r = client.post("/api/auth/login", json={"username": "viewer", "password": "viewer-passphrase"})
    assert r.status_code == 200
    r = client.post("/api/admin/users", json={"username": "x", "password": "passphrase-x"})
    assert r.status_code == 403


def test_newly_created_user_can_log_in(client):
    client.post("/api/admin/users", json={"username": "alice", "password": "alice-passphrase"})
    client.post("/api/auth/logout")
    r = client.post("/api/auth/login", json={"username": "alice", "password": "alice-passphrase"})
    assert r.status_code == 200, r.text
    assert r.json()["username"] == "alice"


# ---- POST /api/auth/change-password ----

def test_change_password_happy_path(client):
    r = client.post("/api/auth/change-password", json={
        "old_password": "correct-horse", "new_password": "new-strong-pw",
    })
    assert r.status_code == 200
    # Logout, login with NEW password works
    client.post("/api/auth/logout")
    r = client.post("/api/auth/login", json={"username": "admin", "password": "new-strong-pw"})
    assert r.status_code == 200
    # Old password no longer works
    client.post("/api/auth/logout")
    r = client.post("/api/auth/login", json={"username": "admin", "password": "correct-horse"})
    assert r.status_code == 401


def test_change_password_requires_old_pw(client):
    r = client.post("/api/auth/change-password", json={
        "old_password": "WRONG", "new_password": "new-strong-pw",
    })
    assert r.status_code == 403


def test_change_password_rejects_short_new(client):
    r = client.post("/api/auth/change-password", json={
        "old_password": "correct-horse", "new_password": "short",
    })
    assert r.status_code == 400


def test_change_password_unauthenticated_is_401(client):
    client.post("/api/auth/logout")
    r = client.post("/api/auth/change-password", json={
        "old_password": "correct-horse", "new_password": "new-strong-pw",
    })
    assert r.status_code == 401
