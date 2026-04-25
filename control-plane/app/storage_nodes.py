"""Repository for nodes + organizations (M5.5)."""
from __future__ import annotations

import aiosqlite
import secrets
import time
from typing import Any


class NodeNotFound(KeyError):
    pass


class OrgNotFound(KeyError):
    pass


class NodeAlreadyExists(ValueError):
    pass


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


class NodesRepository:
    def __init__(self, path: str) -> None:
        self.path = path

    async def upsert_user_node(
        self, *, host_id: str, owner_user_id: str, label: str | None = None,
    ) -> dict[str, Any]:
        """Idempotent: if a node row for this host_id already exists, return it
        unchanged. Otherwise create a new one of node_type='user' owned by
        the given user. Used by the daemon-connect path to auto-register."""
        existing = await self.get_by_host_id(host_id)
        if existing is not None:
            return existing
        nid = _new_id("nod")
        now = time.time()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            try:
                await db.execute(
                    "INSERT INTO nodes(id, host_id, node_type, owner_user_id, "
                    "owner_org_id, label, created_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (nid, host_id, "user", owner_user_id, None, label, now),
                )
                await db.commit()
            except aiosqlite.IntegrityError as e:
                raise NodeAlreadyExists(f"node for host '{host_id}' exists") from e
        return await self.get(nid)

    async def create_shared_node(
        self, *, host_id: str, owner_org_id: str, label: str | None = None,
    ) -> dict[str, Any]:
        nid = _new_id("nod")
        now = time.time()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            try:
                await db.execute(
                    "INSERT INTO nodes(id, host_id, node_type, owner_user_id, "
                    "owner_org_id, label, created_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (nid, host_id, "shared", None, owner_org_id, label, now),
                )
                await db.commit()
            except aiosqlite.IntegrityError as e:
                raise NodeAlreadyExists(f"node for host '{host_id}' exists") from e
        return await self.get(nid)

    async def get(self, node_id: str) -> dict[str, Any]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT id, host_id, node_type, owner_user_id, owner_org_id, "
                "label, created_at FROM nodes WHERE id=?",
                (node_id,),
            ) as cur:
                row = await cur.fetchone()
        if row is None:
            raise NodeNotFound(node_id)
        return _row_to_node(row)

    async def get_by_host_id(self, host_id: str) -> dict[str, Any] | None:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT id, host_id, node_type, owner_user_id, owner_org_id, "
                "label, created_at FROM nodes WHERE host_id=?",
                (host_id,),
            ) as cur:
                row = await cur.fetchone()
        return _row_to_node(row) if row else None

    async def list_visible_to(self, user_id: str, *, is_admin: bool = False) -> list[dict[str, Any]]:
        """Visibility rules:
        - owner_user_id == user_id (user nodes you own)
        - shared nodes: visible if user is a member of the owner org
        - explicit node_access grants
        - admins see everything
        """
        if is_admin:
            return await self._list_all()
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT n.id, n.host_id, n.node_type, n.owner_user_id, n.owner_org_id, "
                "n.label, n.created_at "
                "FROM nodes n "
                "WHERE n.owner_user_id = ? "
                "   OR n.id IN (SELECT node_id FROM node_access WHERE user_id = ?) "
                "   OR (n.node_type = 'shared' AND n.owner_org_id IN ("
                "       SELECT org_id FROM org_members WHERE user_id = ?)) "
                "ORDER BY n.created_at ASC",
                (user_id, user_id, user_id),
            ) as cur:
                rows = await cur.fetchall()
        return [_row_to_node(r) for r in rows]

    async def _list_all(self) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT id, host_id, node_type, owner_user_id, owner_org_id, "
                "label, created_at FROM nodes ORDER BY created_at ASC"
            ) as cur:
                rows = await cur.fetchall()
        return [_row_to_node(r) for r in rows]

    async def grant_access(self, node_id: str, user_id: str, role: str = "viewer") -> None:
        if role not in ("viewer", "operator", "admin"):
            raise ValueError(f"invalid role: {role}")
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO node_access(node_id, user_id, role) "
                "VALUES (?,?,?)",
                (node_id, user_id, role),
            )
            await db.commit()

    async def can_user_see_host(self, user_id: str, host_id: str, *, is_admin: bool = False) -> bool:
        if is_admin:
            return True
        node = await self.get_by_host_id(host_id)
        if node is None:
            # Unknown host: only admins can target it (we still return False here;
            # admin path is short-circuited above).
            return False
        if node["owner_user_id"] == user_id:
            return True
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT 1 FROM node_access WHERE node_id=? AND user_id=?",
                (node["id"], user_id),
            ) as cur:
                if await cur.fetchone() is not None:
                    return True
            if node["node_type"] == "shared" and node["owner_org_id"]:
                async with db.execute(
                    "SELECT 1 FROM org_members WHERE org_id=? AND user_id=?",
                    (node["owner_org_id"], user_id),
                ) as cur2:
                    return (await cur2.fetchone()) is not None
        return False


def _row_to_node(row) -> dict[str, Any]:
    return {
        "id": row[0],
        "host_id": row[1],
        "node_type": row[2],
        "owner_user_id": row[3],
        "owner_org_id": row[4],
        "label": row[5],
        "created_at": row[6],
    }


class OrganizationsRepository:
    def __init__(self, path: str) -> None:
        self.path = path

    async def create(self, name: str) -> dict[str, Any]:
        oid = _new_id("org")
        now = time.time()
        async with aiosqlite.connect(self.path) as db:
            try:
                await db.execute(
                    "INSERT INTO organizations(id, name, created_at) VALUES (?,?,?)",
                    (oid, name, now),
                )
                await db.commit()
            except aiosqlite.IntegrityError as e:
                raise ValueError(f"organization name '{name}' already taken") from e
        return await self.get(oid)

    async def get(self, org_id: str) -> dict[str, Any]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT id, name, created_at FROM organizations WHERE id=?",
                (org_id,),
            ) as cur:
                row = await cur.fetchone()
        if row is None:
            raise OrgNotFound(org_id)
        return {"id": row[0], "name": row[1], "created_at": row[2]}

    async def list_all(self) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT id, name, created_at FROM organizations ORDER BY created_at ASC"
            ) as cur:
                rows = await cur.fetchall()
        return [{"id": r[0], "name": r[1], "created_at": r[2]} for r in rows]

    async def add_member(self, org_id: str, user_id: str, role: str = "member") -> None:
        if role not in ("member", "admin"):
            raise ValueError(f"invalid role: {role}")
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO org_members(org_id, user_id, role) "
                "VALUES (?,?,?)",
                (org_id, user_id, role),
            )
            await db.commit()

    async def list_members(self, org_id: str) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT user_id, role FROM org_members WHERE org_id=?",
                (org_id,),
            ) as cur:
                rows = await cur.fetchall()
        return [{"user_id": r[0], "role": r[1]} for r in rows]
