"""Minimal persistence: last applied deployment YAML, deploy history."""
from __future__ import annotations

import aiosqlite
import time
import json


_SCHEMA = """
-- Legacy tables (kept for backward compat during M1; removed in M2+)
CREATE TABLE IF NOT EXISTS config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    project TEXT,
    yaml_text TEXT NOT NULL,
    applied_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS deploy_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project TEXT,
    ok INTEGER NOT NULL,
    result_json TEXT NOT NULL,
    ts REAL NOT NULL
);

-- New multi-deploy schema (M1)
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE,
    password_hash TEXT,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL DEFAULT (strftime('%s','now'))
);

CREATE TABLE IF NOT EXISTS deploys (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner_user_id TEXT NOT NULL REFERENCES users(id),
    current_version INTEGER,
    state_summary TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(owner_user_id, name)
);

CREATE TABLE IF NOT EXISTS deploy_versions (
    id TEXT PRIMARY KEY,
    deploy_id TEXT NOT NULL REFERENCES deploys(id) ON DELETE CASCADE,
    version_n INTEGER NOT NULL,
    yaml_text TEXT NOT NULL,
    components_hash TEXT NOT NULL,
    parent_version_id TEXT REFERENCES deploy_versions(id),
    applied_at REAL NOT NULL,
    applied_by_user_id TEXT NOT NULL REFERENCES users(id),
    result_json TEXT,
    kind TEXT NOT NULL DEFAULT 'apply',
    UNIQUE(deploy_id, version_n)
);

CREATE INDEX IF NOT EXISTS idx_deploy_versions_deploy ON deploy_versions(deploy_id, version_n DESC);
"""

_SEED_SINGLEUSER = """
INSERT OR IGNORE INTO users (id, username, is_admin, created_at)
VALUES ('singleuser', 'singleuser', 1, strftime('%s','now'));
"""


class Storage:
    def __init__(self, path: str = "control-plane.db"):
        self.path = path

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(_SCHEMA)
            await db.executescript(_SEED_SINGLEUSER)
            await db.execute("PRAGMA foreign_keys = ON;")
            await db.commit()
        from .storage_migrate import migrate_legacy_config_to_default_deploy
        await migrate_legacy_config_to_default_deploy(self.path)

    async def save_config(self, project: str, yaml_text: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO config(id, project, yaml_text, applied_at) VALUES (1, ?, ?, ?)",
                (project, yaml_text, time.time()),
            )
            await db.commit()

    async def load_config(self) -> tuple[str, str, float] | None:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT project, yaml_text, applied_at FROM config WHERE id=1"
            ) as cur:
                row = await cur.fetchone()
                if row is None:
                    return None
                return row[0], row[1], row[2]

    async def record_deploy(self, project: str, ok: bool, result: dict) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "INSERT INTO deploy_history(project, ok, result_json, ts) VALUES (?, ?, ?, ?)",
                (project, 1 if ok else 0, json.dumps(result), time.time()),
            )
            await db.commit()
            return cur.lastrowid

    async def history(self, limit: int = 20) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT id, project, ok, result_json, ts FROM deploy_history "
                "ORDER BY id DESC LIMIT ?", (limit,)
            ) as cur:
                rows = await cur.fetchall()
        return [
            {"id": r[0], "project": r[1], "ok": bool(r[2]),
             "result": json.loads(r[3]), "ts": r[4]}
            for r in rows
        ]
