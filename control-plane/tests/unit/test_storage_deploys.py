import asyncio
import os
import tempfile
import pytest
import aiosqlite

from app.storage import Storage


@pytest.mark.asyncio
async def test_init_creates_schema_and_singleuser():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")
        s = Storage(path)
        await s.init()

        async with aiosqlite.connect(path) as db:
            async with db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ) as cur:
                tables = [r[0] for r in await cur.fetchall()]

            async with db.execute("SELECT id, username, is_admin FROM users") as cur:
                users = await cur.fetchall()

        assert "users" in tables
        assert "deploys" in tables
        assert "deploy_versions" in tables
        # legacy tables preserved for backward compat
        assert "config" in tables
        assert "deploy_history" in tables

        assert users == [("singleuser", "singleuser", 1)]
