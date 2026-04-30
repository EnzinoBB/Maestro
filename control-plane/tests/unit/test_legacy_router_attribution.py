import os
import tempfile
import asyncio
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("MAESTRO_DB", os.path.join(td, "t.db"))
        monkeypatch.setenv("MAESTRO_METRICS_RETENTION_INTERVAL_S", "3600")
        app = create_app()
        with TestClient(app) as c:
            r = c.post("/api/auth/setup-admin",
                       json={"username": "alice", "password": "correct-horse"})
            assert r.status_code == 200
            yield c, r.json()["id"]


def test_legacy_apply_records_real_user_in_audit(client):
    c, alice_id = client
    yaml_text = """api_version: maestro/v1
project: test-audit
hosts:
  host1:
    type: linux
    address: 127.0.0.1
    user: deploy
components:
  web:
    source:
      type: docker
      image: nginx
    run:
      type: docker
      container_name: test
deployment:
  - host: host1
    components: [web]
"""
    r = c.post("/api/config/apply", content=yaml_text,
               headers={"content-type": "text/yaml"})
    assert r.status_code == 200, r.text

    import aiosqlite

    async def _last_applied_by():
        async with aiosqlite.connect(os.environ["MAESTRO_DB"]) as db:
            async with db.execute(
                "SELECT applied_by_user_id FROM deploy_versions "
                "ORDER BY applied_at DESC LIMIT 1"
            ) as cur:
                row = await cur.fetchone()
                return row[0] if row else None

    assert asyncio.run(_last_applied_by()) == alice_id
