"""Repository for the users table (added in M1 schema, populated in M5)."""
from __future__ import annotations

import aiosqlite
import secrets
import time
from typing import Any


class UserNotFound(KeyError):
    pass


class UserAlreadyExists(ValueError):
    pass


def _new_id(prefix: str = "usr") -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


class UsersRepository:
    def __init__(self, path: str) -> None:
        self.path = path

    async def create(
        self, *, username: str, password_hash: str,
        email: str | None = None, is_admin: bool = False,
    ) -> dict[str, Any]:
        uid = _new_id()
        now = time.time()
        async with aiosqlite.connect(self.path) as db:
            try:
                await db.execute(
                    "INSERT INTO users(id, username, email, password_hash, is_admin, created_at) "
                    "VALUES (?,?,?,?,?,?)",
                    (uid, username, email, password_hash, 1 if is_admin else 0, now),
                )
                await db.commit()
            except aiosqlite.IntegrityError as e:
                raise UserAlreadyExists(f"username '{username}' or email already taken") from e
        return await self.get(uid)

    async def set_password(self, user_id: str, password_hash: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "UPDATE users SET password_hash=? WHERE id=?",
                (password_hash, user_id),
            )
            await db.commit()
        if cur.rowcount == 0:
            raise UserNotFound(user_id)

    async def get(self, user_id: str) -> dict[str, Any]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT id, username, email, password_hash, is_admin, created_at "
                "FROM users WHERE id=?",
                (user_id,),
            ) as cur:
                row = await cur.fetchone()
        if row is None:
            raise UserNotFound(user_id)
        return _row_to_user(row)

    async def get_by_username(self, username: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT id, username, email, password_hash, is_admin, created_at "
                "FROM users WHERE username=?",
                (username,),
            ) as cur:
                row = await cur.fetchone()
        return _row_to_user(row) if row else None

    async def set_admin(self, user_id: str, is_admin: bool) -> None:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "UPDATE users SET is_admin=? WHERE id=?",
                (1 if is_admin else 0, user_id),
            )
            await db.commit()
        if cur.rowcount == 0:
            raise UserNotFound(user_id)

    async def delete(self, user_id: str) -> None:
        """Delete a user. Cascades clear api_keys, org_members, node_access.

        deploy_versions.applied_by_user_id has no cascade — those rows are
        first re-attributed to the 'singleuser' system row to preserve audit
        history. The caller must already have ensured the user owns no live
        deploys/nodes; otherwise the FK constraints on `deploys.owner_user_id`
        and `nodes.owner_user_id` (no cascade) will raise IntegrityError.
        """
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            await db.execute(
                "UPDATE deploy_versions SET applied_by_user_id='singleuser' "
                "WHERE applied_by_user_id=?",
                (user_id,),
            )
            cur = await db.execute("DELETE FROM users WHERE id=?", (user_id,))
            await db.commit()
        if cur.rowcount == 0:
            raise UserNotFound(user_id)

    async def count_dependencies(self, user_id: str) -> dict[str, int]:
        """Counts of records that block deletion (non-cascade FKs).

        Returns counts of deploys and nodes owned by the user. Both must be
        zero before delete() can succeed.
        """
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM deploys WHERE owner_user_id=?", (user_id,),
            ) as cur:
                deploys = (await cur.fetchone())[0]
            async with db.execute(
                "SELECT COUNT(*) FROM nodes WHERE owner_user_id=?", (user_id,),
            ) as cur:
                nodes = (await cur.fetchone())[0]
        return {"deploys": int(deploys), "nodes": int(nodes)}

    async def count_non_singleuser(self) -> int:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM users WHERE id != 'singleuser'"
            ) as cur:
                return (await cur.fetchone())[0]


def _row_to_user(row) -> dict[str, Any]:
    return {
        "id": row[0],
        "username": row[1],
        "email": row[2],
        "password_hash": row[3],
        "is_admin": bool(row[4]),
        "created_at": row[5],
    }
