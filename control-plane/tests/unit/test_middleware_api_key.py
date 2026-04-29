import os
import tempfile
import time
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.auth.passwords import hash_password


@pytest.fixture
def env(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("MAESTRO_DB", os.path.join(td, "t.db"))
        monkeypatch.setenv("MAESTRO_METRICS_RETENTION_INTERVAL_S", "3600")
        app = create_app()
        with TestClient(app) as c:
            # Seed an admin and an API key for them
            r = c.post(
                "/api/auth/setup-admin",
                json={"username": "alice", "password": "correct-horse"},
            )
            assert r.status_code == 200
            user_id = r.json()["id"]
            # Drop the cookie so subsequent requests are anonymous unless Bearer
            c.cookies.clear()
            # Insert a key directly via the repo
            import asyncio
            from app.auth.api_keys_repo import ApiKeysRepository
            repo = ApiKeysRepository(os.environ["MAESTRO_DB"])

            async def _seed():
                full_key = "mae_test12345abcdefghijklmnopqrstuvwxyz"
                prefix = full_key[:9]
                khash = hash_password(full_key)
                row = await repo.create(
                    user_id=user_id, label="test", prefix=prefix, key_hash=khash,
                )
                return full_key, row

            full_key, key_row = asyncio.run(_seed())
            yield {"client": c, "user_id": user_id,
                   "full_key": full_key, "key_id": key_row["id"]}


def test_anonymous_request_returns_401(env):
    c = env["client"]
    r = c.get("/api/deploys")
    assert r.status_code == 401


def test_valid_bearer_authenticates(env):
    c = env["client"]
    r = c.get("/api/deploys",
              headers={"Authorization": f"Bearer {env['full_key']}"})
    assert r.status_code == 200


def test_invalid_bearer_returns_401_and_does_not_fallback_to_cookie(env):
    c = env["client"]
    # Login the cookie back in
    c.post("/api/auth/login",
           json={"username": "alice", "password": "correct-horse"})
    # Send a bogus Bearer alongside the valid cookie:
    # the request must fail because Bearer-presence forces key-auth path.
    r = c.get("/api/deploys",
              headers={"Authorization": "Bearer mae_completely_bogus_xxx"})
    assert r.status_code == 401


def test_revoked_key_returns_401(env):
    c = env["client"]
    import asyncio
    from app.auth.api_keys_repo import ApiKeysRepository
    repo = ApiKeysRepository(os.environ["MAESTRO_DB"])
    asyncio.run(repo.revoke(env["key_id"], user_id=env["user_id"]))
    r = c.get("/api/deploys",
              headers={"Authorization": f"Bearer {env['full_key']}"})
    assert r.status_code == 401


def test_bearer_updates_last_used(env):
    c = env["client"]
    import asyncio
    from app.auth.api_keys_repo import ApiKeysRepository
    repo = ApiKeysRepository(os.environ["MAESTRO_DB"])
    before = asyncio.run(repo.get(env["key_id"]))
    assert before["last_used_at"] is None

    r = c.get("/api/deploys",
              headers={"Authorization": f"Bearer {env['full_key']}"})
    assert r.status_code == 200

    # last_used_at update is fire-and-forget; give the loop a tick
    import time as _t
    for _ in range(20):
        _t.sleep(0.05)
        after = asyncio.run(repo.get(env["key_id"]))
        if after["last_used_at"] is not None:
            break
    assert after["last_used_at"] is not None
