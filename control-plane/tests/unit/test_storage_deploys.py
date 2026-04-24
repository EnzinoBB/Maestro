import os
import tempfile
import pytest
import aiosqlite

from app.storage import Storage
from app.storage_deploys import DeployRepository, DeployNotFound


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


@pytest.mark.asyncio
async def test_create_deploy_returns_row_with_empty_version_chain():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")
        s = Storage(path)
        await s.init()
        repo = DeployRepository(path)

        d = await repo.create("webapp-prod", owner_user_id="singleuser")

        assert d["name"] == "webapp-prod"
        assert d["owner_user_id"] == "singleuser"
        assert d["current_version"] is None
        assert d["id"]
        assert d["created_at"] and d["updated_at"]

        fetched = await repo.get(d["id"])
        assert fetched["name"] == "webapp-prod"

        versions = await repo.list_versions(d["id"])
        assert versions == []


@pytest.mark.asyncio
async def test_create_deploy_duplicate_name_for_same_owner_fails():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")
        await Storage(path).init()
        repo = DeployRepository(path)

        await repo.create("webapp-prod", owner_user_id="singleuser")
        with pytest.raises(ValueError, match="already exists"):
            await repo.create("webapp-prod", owner_user_id="singleuser")


@pytest.mark.asyncio
async def test_get_nonexistent_raises():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")
        await Storage(path).init()
        repo = DeployRepository(path)

        with pytest.raises(DeployNotFound):
            await repo.get("does-not-exist")


@pytest.mark.asyncio
async def test_get_by_name_returns_none_when_missing():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")
        await Storage(path).init()
        repo = DeployRepository(path)
        result = await repo.get_by_name("singleuser", "nope")
        assert result is None


@pytest.mark.asyncio
async def test_list_for_owner_returns_only_owned():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")
        await Storage(path).init()
        # Seed a second user directly
        async with aiosqlite.connect(path) as db:
            await db.execute(
                "INSERT INTO users(id, username, is_admin, created_at) "
                "VALUES ('u2','u2',0, strftime('%s','now'))"
            )
            await db.commit()
        repo = DeployRepository(path)
        await repo.create("mine", owner_user_id="singleuser")
        await repo.create("theirs", owner_user_id="u2")
        mine = await repo.list_for_owner("singleuser")
        theirs = await repo.list_for_owner("u2")
        assert [d["name"] for d in mine] == ["mine"]
        assert [d["name"] for d in theirs] == ["theirs"]


@pytest.mark.asyncio
async def test_delete_deploy_cascades_versions():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")
        await Storage(path).init()
        repo = DeployRepository(path)

        d = await repo.create("app", owner_user_id="singleuser")
        await repo.append_version(
            d["id"], yaml_text="y", components_hash="h",
            applied_by_user_id="singleuser", result_json=None,
        )
        await repo.delete(d["id"])
        with pytest.raises(DeployNotFound):
            await repo.get(d["id"])
        # Versions must be gone too (FK ON DELETE CASCADE)
        async with aiosqlite.connect(path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM deploy_versions WHERE deploy_id=?", (d["id"],)
            ) as cur:
                count = (await cur.fetchone())[0]
        assert count == 0


@pytest.mark.asyncio
async def test_delete_nonexistent_raises():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")
        await Storage(path).init()
        repo = DeployRepository(path)
        with pytest.raises(DeployNotFound):
            await repo.delete("nope")
