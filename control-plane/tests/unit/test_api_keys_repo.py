import os
import tempfile
import time
import pytest

from app.storage import Storage
from app.auth.api_keys_repo import ApiKeysRepository, ApiKeyNotFound


@pytest.fixture
async def repo():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")
        s = Storage(path)
        await s.init()
        # Seed a non-singleuser user so FK is satisfied
        import aiosqlite
        async with aiosqlite.connect(path) as db:
            await db.execute(
                "INSERT INTO users (id, username, is_admin, created_at) "
                "VALUES (?,?,?,?)",
                ("usr_alice", "alice", 0, time.time()),
            )
            await db.commit()
        yield ApiKeysRepository(path)


@pytest.mark.asyncio
async def test_create_returns_id_and_metadata(repo):
    row = await repo.create(
        user_id="usr_alice", label="laptop", prefix="mae_abc12",
        key_hash="hashed",
    )
    assert row["id"].startswith("ak_")
    assert row["user_id"] == "usr_alice"
    assert row["label"] == "laptop"
    assert row["prefix"] == "mae_abc12"
    assert row["revoked_at"] is None
    assert row["last_used_at"] is None
    assert row["created_at"] > 0


@pytest.mark.asyncio
async def test_list_active_by_user_excludes_revoked(repo):
    a = await repo.create(user_id="usr_alice", label="a", prefix="mae_aaa11", key_hash="h1")
    b = await repo.create(user_id="usr_alice", label="b", prefix="mae_bbb22", key_hash="h2")
    await repo.revoke(b["id"], user_id="usr_alice")
    rows = await repo.list_by_user("usr_alice")
    assert {r["id"] for r in rows} == {a["id"], b["id"]}  # both visible
    active = [r for r in rows if r["revoked_at"] is None]
    assert {r["id"] for r in active} == {a["id"]}


@pytest.mark.asyncio
async def test_list_active_by_prefix_finds_match(repo):
    created = await repo.create(user_id="usr_alice", label="a", prefix="mae_xyz98", key_hash="h")
    rows = await repo.list_active_by_prefix("mae_xyz98")
    assert len(rows) == 1
    assert rows[0]["id"] == created["id"]


@pytest.mark.asyncio
async def test_list_active_by_prefix_skips_revoked(repo):
    created = await repo.create(user_id="usr_alice", label="a", prefix="mae_xyz98", key_hash="h")
    await repo.revoke(created["id"], user_id="usr_alice")
    rows = await repo.list_active_by_prefix("mae_xyz98")
    assert rows == []


@pytest.mark.asyncio
async def test_revoke_is_idempotent(repo):
    k = await repo.create(user_id="usr_alice", label="a", prefix="mae_qqq11", key_hash="h")
    await repo.revoke(k["id"], user_id="usr_alice")
    # Second revoke must not raise
    await repo.revoke(k["id"], user_id="usr_alice")


@pytest.mark.asyncio
async def test_revoke_other_users_key_does_not_change_state(repo):
    k = await repo.create(user_id="usr_alice", label="a", prefix="mae_qqq11", key_hash="h")
    # Different user attempts revoke
    await repo.revoke(k["id"], user_id="usr_bob")
    rows = await repo.list_by_user("usr_alice")
    assert rows[0]["revoked_at"] is None  # untouched


@pytest.mark.asyncio
async def test_touch_last_used_updates_timestamp(repo):
    k = await repo.create(user_id="usr_alice", label="a", prefix="mae_qqq11", key_hash="h")
    assert k["last_used_at"] is None
    await repo.touch_last_used(k["id"])
    rows = await repo.list_by_user("usr_alice")
    assert rows[0]["last_used_at"] is not None


@pytest.mark.asyncio
async def test_count_active_by_user(repo):
    await repo.create(user_id="usr_alice", label="a", prefix="mae_aaa", key_hash="h")
    b = await repo.create(user_id="usr_alice", label="b", prefix="mae_bbb", key_hash="h")
    assert await repo.count_active_by_user("usr_alice") == 2
    await repo.revoke(b["id"], user_id="usr_alice")
    assert await repo.count_active_by_user("usr_alice") == 1


@pytest.mark.asyncio
async def test_label_unique_per_user_among_active(repo):
    await repo.create(user_id="usr_alice", label="laptop", prefix="mae_aaa", key_hash="h")
    with pytest.raises(ValueError):
        await repo.create(user_id="usr_alice", label="laptop", prefix="mae_bbb", key_hash="h")


@pytest.mark.asyncio
async def test_label_can_be_reused_after_revoke(repo):
    a = await repo.create(user_id="usr_alice", label="laptop", prefix="mae_aaa", key_hash="h")
    await repo.revoke(a["id"], user_id="usr_alice")
    # Reusing the same label is fine now
    await repo.create(user_id="usr_alice", label="laptop", prefix="mae_bbb", key_hash="h")
