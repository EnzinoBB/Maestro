"""Repository for the multi-deploy data model (deploys + deploy_versions)."""
from __future__ import annotations

import aiosqlite
import json
import secrets
import time
from typing import Any


class DeployNotFound(KeyError):
    """Raised when a deploy with the given id does not exist."""


class DeployVersionNotFound(KeyError):
    """Raised when a (deploy_id, version_n) does not exist."""


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


class DeployRepository:
    def __init__(self, path: str) -> None:
        self.path = path

    async def create(self, name: str, *, owner_user_id: str) -> dict[str, Any]:
        deploy_id = _new_id("dep")
        now = time.time()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            try:
                await db.execute(
                    "INSERT INTO deploys(id, name, owner_user_id, current_version, "
                    "state_summary, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                    (deploy_id, name, owner_user_id, None, None, now, now),
                )
                await db.commit()
            except aiosqlite.IntegrityError as e:
                raise ValueError(
                    f"deploy name '{name}' already exists for owner {owner_user_id}"
                ) from e
        return await self.get(deploy_id)

    async def get(self, deploy_id: str) -> dict[str, Any]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT id, name, owner_user_id, current_version, state_summary, "
                "created_at, updated_at FROM deploys WHERE id=?",
                (deploy_id,),
            ) as cur:
                row = await cur.fetchone()
        if row is None:
            raise DeployNotFound(deploy_id)
        return _row_to_deploy(row)

    async def list_for_owner(self, owner_user_id: str) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT id, name, owner_user_id, current_version, state_summary, "
                "created_at, updated_at FROM deploys WHERE owner_user_id=? "
                "ORDER BY created_at ASC",
                (owner_user_id,),
            ) as cur:
                rows = await cur.fetchall()
        return [_row_to_deploy(r) for r in rows]

    async def get_by_name(self, owner_user_id: str, name: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT id FROM deploys WHERE owner_user_id=? AND name=?",
                (owner_user_id, name),
            ) as cur:
                row = await cur.fetchone()
        if row is None:
            return None
        return await self.get(row[0])

    async def delete(self, deploy_id: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            cur = await db.execute("DELETE FROM deploys WHERE id=?", (deploy_id,))
            await db.commit()
        if cur.rowcount == 0:
            raise DeployNotFound(deploy_id)

    # ---------- versions ----------

    async def list_versions(self, deploy_id: str) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT id, version_n, yaml_text, components_hash, parent_version_id, "
                "applied_at, applied_by_user_id, result_json, kind "
                "FROM deploy_versions WHERE deploy_id=? ORDER BY version_n ASC",
                (deploy_id,),
            ) as cur:
                rows = await cur.fetchall()
        return [_row_to_version(r) for r in rows]

    async def get_version(self, deploy_id: str, version_n: int) -> dict[str, Any]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT id, version_n, yaml_text, components_hash, parent_version_id, "
                "applied_at, applied_by_user_id, result_json, kind "
                "FROM deploy_versions WHERE deploy_id=? AND version_n=?",
                (deploy_id, version_n),
            ) as cur:
                row = await cur.fetchone()
        if row is None:
            raise DeployVersionNotFound((deploy_id, version_n))
        return _row_to_version(row)

    async def append_version(
        self,
        deploy_id: str,
        *,
        yaml_text: str,
        components_hash: str,
        applied_by_user_id: str,
        result_json: dict[str, Any] | None,
        kind: str = "apply",
        parent_version_id: str | None = None,
    ) -> dict[str, Any]:
        assert kind in ("apply", "rollback"), f"invalid kind: {kind}"
        version_id = _new_id("ver")
        now = time.time()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            async with db.execute(
                "SELECT COALESCE(MAX(version_n), 0) + 1 FROM deploy_versions WHERE deploy_id=?",
                (deploy_id,),
            ) as cur:
                next_n = (await cur.fetchone())[0]

            resolved_parent = parent_version_id
            if resolved_parent is None and next_n > 1:
                async with db.execute(
                    "SELECT id FROM deploy_versions WHERE deploy_id=? AND version_n=?",
                    (deploy_id, next_n - 1),
                ) as cur2:
                    prev = await cur2.fetchone()
                    if prev is not None:
                        resolved_parent = prev[0]

            await db.execute(
                "INSERT INTO deploy_versions(id, deploy_id, version_n, yaml_text, "
                "components_hash, parent_version_id, applied_at, applied_by_user_id, "
                "result_json, kind) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    version_id, deploy_id, next_n, yaml_text, components_hash,
                    resolved_parent, now, applied_by_user_id,
                    json.dumps(result_json) if result_json is not None else None,
                    kind,
                ),
            )
            await db.execute(
                "UPDATE deploys SET current_version=?, updated_at=? WHERE id=?",
                (next_n, now, deploy_id),
            )
            await db.commit()

        return await self.get_version(deploy_id, next_n)

    async def set_state_summary(self, deploy_id: str, summary: dict[str, Any]) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE deploys SET state_summary=?, updated_at=? WHERE id=?",
                (json.dumps(summary), time.time(), deploy_id),
            )
            await db.commit()


def _row_to_deploy(row) -> dict[str, Any]:
    return {
        "id": row[0],
        "name": row[1],
        "owner_user_id": row[2],
        "current_version": row[3],
        "state_summary": json.loads(row[4]) if row[4] else None,
        "created_at": row[5],
        "updated_at": row[6],
    }


def _row_to_version(row) -> dict[str, Any]:
    return {
        "id": row[0],
        "version_n": row[1],
        "yaml_text": row[2],
        "components_hash": row[3],
        "parent_version_id": row[4],
        "applied_at": row[5],
        "applied_by_user_id": row[6],
        "result_json": json.loads(row[7]) if row[7] else None,
        "kind": row[8],
    }
