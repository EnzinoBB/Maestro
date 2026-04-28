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
            r = c.post("/api/auth/setup-admin",
                       json={"username": "alice", "password": "correct-horse"})
            assert r.status_code == 200
            yield c


def test_post_keys_creates_and_returns_clear_key(client):
    r = client.post("/api/auth/keys", json={"label": "laptop"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["label"] == "laptop"
    assert body["key"].startswith("mae_")
    assert len(body["key"]) >= 40
    assert body["prefix"] == body["key"][:9]
    assert "warning" in body


def test_post_keys_rejects_empty_label(client):
    r = client.post("/api/auth/keys", json={"label": ""})
    assert r.status_code == 400


def test_post_keys_rejects_label_over_64_chars(client):
    r = client.post("/api/auth/keys", json={"label": "x" * 65})
    assert r.status_code == 400


def test_post_keys_rejects_duplicate_active_label(client):
    r = client.post("/api/auth/keys", json={"label": "laptop"})
    assert r.status_code == 201
    r = client.post("/api/auth/keys", json={"label": "laptop"})
    assert r.status_code == 409


def test_post_keys_enforces_max_active_keys(client):
    for i in range(10):
        r = client.post("/api/auth/keys", json={"label": f"k{i}"})
        assert r.status_code == 201, r.text
    r = client.post("/api/auth/keys", json={"label": "k10"})
    assert r.status_code == 409
    body = r.json()
    assert body["error"]["code"] == "conflict"


def test_post_keys_requires_auth(client):
    client.cookies.clear()
    r = client.post("/api/auth/keys", json={"label": "laptop"})
    assert r.status_code == 401


def test_get_keys_returns_own_keys_only(client):
    client.post("/api/auth/keys", json={"label": "a"})
    client.post("/api/auth/keys", json={"label": "b"})

    r = client.get("/api/auth/keys")
    assert r.status_code == 200
    body = r.json()
    labels = sorted(k["label"] for k in body["keys"])
    assert labels == ["a", "b"]
    # Cleartext key MUST NOT appear in list
    for k in body["keys"]:
        assert "key" not in k
        assert "key_hash" not in k


def test_get_keys_includes_revoked(client):
    r = client.post("/api/auth/keys", json={"label": "a"})
    kid = r.json()["id"]
    client.delete(f"/api/auth/keys/{kid}")

    r = client.get("/api/auth/keys")
    keys = r.json()["keys"]
    assert len(keys) == 1
    assert keys[0]["revoked_at"] is not None


def test_get_keys_requires_auth(client):
    client.cookies.clear()
    r = client.get("/api/auth/keys")
    assert r.status_code == 401


def test_delete_revokes_key(client):
    r = client.post("/api/auth/keys", json={"label": "x"})
    kid = r.json()["id"]
    full_key = r.json()["key"]

    r = client.delete(f"/api/auth/keys/{kid}")
    assert r.status_code == 204

    # The revoked key no longer authenticates
    client.cookies.clear()
    r = client.get("/api/deploys",
                   headers={"Authorization": f"Bearer {full_key}"})
    assert r.status_code == 401


def test_delete_is_idempotent(client):
    r = client.post("/api/auth/keys", json={"label": "x"})
    kid = r.json()["id"]
    assert client.delete(f"/api/auth/keys/{kid}").status_code == 204
    assert client.delete(f"/api/auth/keys/{kid}").status_code == 204


def test_delete_other_users_key_returns_404(client, monkeypatch):
    # Create a second user and a key owned by them.
    import asyncio
    from app.auth.api_keys_repo import ApiKeysRepository
    from app.auth.passwords import hash_password
    repo = ApiKeysRepository(os.environ["MAESTRO_DB"])
    import aiosqlite
    import time as _t

    async def _seed():
        async with aiosqlite.connect(os.environ["MAESTRO_DB"]) as db:
            await db.execute(
                "INSERT INTO users (id, username, is_admin, created_at) "
                "VALUES (?,?,?,?)",
                ("usr_bob", "bob", 0, _t.time()),
            )
            await db.commit()
        return await repo.create(user_id="usr_bob", label="bobs",
                                 prefix="mae_bob01", key_hash=hash_password("mae_bob01xxxx"))

    bobs_key = asyncio.run(_seed())

    # alice (the test client) tries to revoke bob's key
    r = client.delete(f"/api/auth/keys/{bobs_key['id']}")
    assert r.status_code == 404


def test_delete_requires_auth(client):
    client.cookies.clear()
    r = client.delete("/api/auth/keys/ak_nonexistent")
    assert r.status_code == 401
