"""Minimal persistence: last applied deployment YAML, deploy history."""
from __future__ import annotations

import aiosqlite
from pathlib import Path
import time
import json


_SCHEMA = """
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
"""


class Storage:
    def __init__(self, path: str = "control-plane.db"):
        self.path = path

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(_SCHEMA)
            await db.commit()

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
