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

-- Metrics (M2)
CREATE TABLE IF NOT EXISTS metric_samples (
    ts          REAL NOT NULL,
    scope       TEXT NOT NULL,            -- 'host' | 'component' | 'deploy'
    scope_id    TEXT NOT NULL,
    metric      TEXT NOT NULL,
    value       REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metric_samples_lookup
    ON metric_samples(scope, scope_id, metric, ts);

CREATE TABLE IF NOT EXISTS metric_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            REAL NOT NULL,
    kind          TEXT NOT NULL,
    scope         TEXT NOT NULL,
    scope_id      TEXT NOT NULL,
    payload_json  TEXT
);
CREATE INDEX IF NOT EXISTS idx_metric_events_lookup
    ON metric_events(scope, scope_id, ts DESC);

-- Multi-tenant entities (M5.5)
CREATE TABLE IF NOT EXISTS organizations (
    id          TEXT PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS org_members (
    org_id   TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id  TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role     TEXT NOT NULL DEFAULT 'member',  -- 'admin' | 'member'
    PRIMARY KEY (org_id, user_id)
);

CREATE TABLE IF NOT EXISTS nodes (
    id              TEXT PRIMARY KEY,
    host_id         TEXT UNIQUE NOT NULL,    -- matches the daemon-side host_id
    node_type       TEXT NOT NULL,           -- 'user' | 'shared'
    owner_user_id   TEXT REFERENCES users(id),
    owner_org_id    TEXT REFERENCES organizations(id),
    label           TEXT,                    -- display name override (optional)
    created_at      REAL NOT NULL,
    CHECK (
        (node_type = 'user' AND owner_user_id IS NOT NULL AND owner_org_id IS NULL) OR
        (node_type = 'shared' AND owner_org_id IS NOT NULL AND owner_user_id IS NULL)
    )
);

CREATE TABLE IF NOT EXISTS node_access (
    node_id  TEXT NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    user_id  TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role     TEXT NOT NULL DEFAULT 'viewer',  -- 'viewer' | 'operator' | 'admin'
    PRIMARY KEY (node_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_nodes_owner_user ON nodes(owner_user_id);
CREATE INDEX IF NOT EXISTS idx_nodes_owner_org ON nodes(owner_org_id);

-- Per-user API keys (used by MCP and other automations)
CREATE TABLE IF NOT EXISTS api_keys (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    label        TEXT NOT NULL,
    prefix       TEXT NOT NULL,
    key_hash     TEXT NOT NULL,
    created_at   REAL NOT NULL,
    last_used_at REAL,
    revoked_at   REAL
);
CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_prefix ON api_keys(prefix);
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
