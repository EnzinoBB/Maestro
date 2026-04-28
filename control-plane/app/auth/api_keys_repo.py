"""Repository for the api_keys table."""
from __future__ import annotations

import aiosqlite
import secrets
import time
from typing import Any


class ApiKeyNotFound(KeyError):
    pass


def _new_id() -> str:
    return f"ak_{secrets.token_hex(8)}"


class ApiKeysRepository:
    def __init__(self, path: str) -> None:
        self.path = path

    async def create(
        self, *, user_id: str, label: str, prefix: str, key_hash: str,
    ) -> dict[str, Any]:
        # Enforce label uniqueness among the user's active keys.
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT id FROM api_keys "
                "WHERE user_id=? AND label=? AND revoked_at IS NULL",
                (user_id, label),
            ) as cur:
                if await cur.fetchone():
                    raise ValueError(f"label '{label}' already in use")
            kid = _new_id()
            now = time.time()
            await db.execute(
                "INSERT INTO api_keys "
                "(id, user_id, label, prefix, key_hash, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (kid, user_id, label, prefix, key_hash, now),
            )
            await db.commit()
        return await self.get(kid)

    async def get(self, key_id: str) -> dict[str, Any]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT id, user_id, label, prefix, key_hash, "
                "created_at, last_used_at, revoked_at "
                "FROM api_keys WHERE id=?",
                (key_id,),
            ) as cur:
                row = await cur.fetchone()
        if row is None:
            raise ApiKeyNotFound(key_id)
        return _row_to_key(row)

    async def list_by_user(self, user_id: str) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT id, user_id, label, prefix, key_hash, "
                "created_at, last_used_at, revoked_at "
                "FROM api_keys WHERE user_id=? "
                "ORDER BY created_at DESC",
                (user_id,),
            ) as cur:
                rows = await cur.fetchall()
        return [_row_to_key(r) for r in rows]

    async def list_active_by_prefix(self, prefix: str) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT id, user_id, label, prefix, key_hash, "
                "created_at, last_used_at, revoked_at "
                "FROM api_keys WHERE prefix=? AND revoked_at IS NULL",
                (prefix,),
            ) as cur:
                rows = await cur.fetchall()
        return [_row_to_key(r) for r in rows]

    async def revoke(self, key_id: str, *, user_id: str) -> None:
        """Soft-revoke. Idempotent. Only revokes if the key belongs to user_id."""
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE api_keys SET revoked_at=? "
                "WHERE id=? AND user_id=? AND revoked_at IS NULL",
                (time.time(), key_id, user_id),
            )
            await db.commit()

    async def touch_last_used(self, key_id: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE api_keys SET last_used_at=? WHERE id=?",
                (time.time(), key_id),
            )
            await db.commit()

    async def count_active_by_user(self, user_id: str) -> int:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM api_keys "
                "WHERE user_id=? AND revoked_at IS NULL",
                (user_id,),
            ) as cur:
                return (await cur.fetchone())[0]


def _row_to_key(row) -> dict[str, Any]:
    return {
        "id": row[0],
        "user_id": row[1],
        "label": row[2],
        "prefix": row[3],
        "key_hash": row[4],
        "created_at": row[5],
        "last_used_at": row[6],
        "revoked_at": row[7],
    }
