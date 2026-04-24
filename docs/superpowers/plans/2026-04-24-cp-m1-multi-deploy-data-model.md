# CP v2 M1 — Multi-Deploy Data Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn "deploy" into a first-class named entity with per-deploy version history, preserving backward compatibility with the current `/api/config/*` endpoints.

**Architecture:** Introduce `deploys`, `deploy_versions`, and a stub `users` table in the existing SQLite DB. Add a `DeployRepository` alongside the existing `Storage`. New `/api/deploys/*` routes are the canonical surface; `/api/config/*` becomes a thin shim that reads/writes the deploy named `default` owned by the materialized `singleuser` row. One-time migration copies the existing single `config` row into the new schema on startup.

**Tech Stack:** Python 3.11, FastAPI, aiosqlite, pytest, pytest-asyncio. No new runtime dependencies.

**Spec reference:** [docs/superpowers/specs/2026-04-24-control-plane-v2-vision-design.md](../specs/2026-04-24-control-plane-v2-vision-design.md), §1 and §5 ("Single-user mode").

---

## File Structure

Files created:
- `control-plane/app/storage_deploys.py` — `DeployRepository` class (new; kept separate from the legacy `Storage` class to make the M5 auth migration cleaner)
- `control-plane/app/storage_migrate.py` — one-time legacy-config → deploys migration
- `control-plane/app/api/deploys.py` — new `/api/deploys/*` router
- `control-plane/app/config/cross_deploy_validator.py` — cross-deploy conflict checks
- `control-plane/tests/unit/test_storage_deploys.py` — repo-level unit tests
- `control-plane/tests/unit/test_storage_migrate.py` — migration test
- `control-plane/tests/unit/test_cross_deploy_validator.py` — validator tests
- `control-plane/tests/unit/test_api_deploys.py` — HTTP-level tests for new router
- `control-plane/tests/unit/test_api_config_shim.py` — retro-compat verification

Files modified:
- `control-plane/app/storage.py` — extend `_SCHEMA` with new tables + `init()` triggers migration
- `control-plane/app/main.py` — wire `DeployRepository` into `app.state`, include new router
- `control-plane/app/api/router.py` — refactor `/api/config/apply` and `/api/deploy` to go through `DeployRepository` on the `default` deploy
- `control-plane/app/mcp/server.py` — new optional `deploy_id` parameter on deploy-aware tools (default `default`)

Files unchanged (out of scope for M1):
- `engine.py`, `hub.py`, `config/loader.py`, `config/validator.py`, `ws/*` — the engine still takes a parsed `DeploymentSpec`; the repo wraps a versioned YAML around it.

---

## Task 1: Schema + materialized singleuser

**Files:**
- Modify: `control-plane/app/storage.py:9-23` (replace `_SCHEMA`)
- Test: `control-plane/tests/unit/test_storage_deploys.py` (new)

- [ ] **Step 1: Write the failing test**

Create `control-plane/tests/unit/test_storage_deploys.py`:

```python
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
```

- [ ] **Step 2: Run test, verify it fails**

Run: `cd control-plane && python -m pytest tests/unit/test_storage_deploys.py::test_init_creates_schema_and_singleuser -v`
Expected: FAIL — either `users` table missing or no singleuser row.

- [ ] **Step 3: Replace `_SCHEMA` in `control-plane/app/storage.py`**

Replace the entire `_SCHEMA` constant (lines 9-23) with:

```python
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
    kind TEXT NOT NULL DEFAULT 'apply',  -- 'apply' | 'rollback'
    UNIQUE(deploy_id, version_n)
);

CREATE INDEX IF NOT EXISTS idx_deploy_versions_deploy ON deploy_versions(deploy_id, version_n DESC);
"""

_SINGLEUSER_ID = "singleuser"

_SEED_SINGLEUSER = """
INSERT OR IGNORE INTO users (id, username, is_admin, created_at)
VALUES ('singleuser', 'singleuser', 1, strftime('%s','now'));
"""
```

Then update `Storage.init` to run the seed:

```python
async def init(self) -> None:
    async with aiosqlite.connect(self.path) as db:
        await db.executescript(_SCHEMA)
        await db.executescript(_SEED_SINGLEUSER)
        await db.execute("PRAGMA foreign_keys = ON;")
        await db.commit()
```

- [ ] **Step 4: Run test, verify it passes**

Run: `cd control-plane && python -m pytest tests/unit/test_storage_deploys.py::test_init_creates_schema_and_singleuser -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add control-plane/app/storage.py control-plane/tests/unit/test_storage_deploys.py
git commit -m "feat(cp): add users/deploys/deploy_versions schema + singleuser seed"
```

---

## Task 2: DeployRepository — create + current

**Files:**
- Create: `control-plane/app/storage_deploys.py`
- Modify: `control-plane/tests/unit/test_storage_deploys.py` (append tests)

- [ ] **Step 1: Append failing tests**

Append to `control-plane/tests/unit/test_storage_deploys.py`:

```python
from app.storage_deploys import DeployRepository, DeployNotFound


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
        assert d["id"]  # generated
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
```

- [ ] **Step 2: Run the three new tests, verify they fail**

Run: `cd control-plane && python -m pytest tests/unit/test_storage_deploys.py -v`
Expected: 3 new tests FAIL with `ModuleNotFoundError: app.storage_deploys` or `AttributeError`.

- [ ] **Step 3: Create `control-plane/app/storage_deploys.py`**

```python
"""Repository for the multi-deploy data model (deploys + deploy_versions)."""
from __future__ import annotations

import aiosqlite
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any


class DeployNotFound(KeyError):
    """Raised when a deploy with the given id does not exist."""


class DeployVersionNotFound(KeyError):
    """Raised when a deploy_version with the given (deploy_id, version_n) does not exist."""


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


class DeployRepository:
    """Thin SQL wrapper. Handlers depend on this class, never on SQL directly.

    Every method opens its own connection (same pattern as `Storage`). All times are epoch seconds.
    """

    def __init__(self, path: str) -> None:
        self.path = path

    # ---------- deploys CRUD ----------

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
        return {
            "id": row[0],
            "name": row[1],
            "owner_user_id": row[2],
            "current_version": row[3],
            "state_summary": json.loads(row[4]) if row[4] else None,
            "created_at": row[5],
            "updated_at": row[6],
        }

    async def list_for_owner(self, owner_user_id: str) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT id, name, owner_user_id, current_version, state_summary, "
                "created_at, updated_at FROM deploys WHERE owner_user_id=? "
                "ORDER BY created_at ASC",
                (owner_user_id,),
            ) as cur:
                rows = await cur.fetchall()
        return [
            {
                "id": r[0], "name": r[1], "owner_user_id": r[2],
                "current_version": r[3],
                "state_summary": json.loads(r[4]) if r[4] else None,
                "created_at": r[5], "updated_at": r[6],
            }
            for r in rows
        ]

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
        return [
            {
                "id": r[0], "version_n": r[1], "yaml_text": r[2],
                "components_hash": r[3], "parent_version_id": r[4],
                "applied_at": r[5], "applied_by_user_id": r[6],
                "result_json": json.loads(r[7]) if r[7] else None,
                "kind": r[8],
            }
            for r in rows
        ]

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
        return {
            "id": row[0], "version_n": row[1], "yaml_text": row[2],
            "components_hash": row[3], "parent_version_id": row[4],
            "applied_at": row[5], "applied_by_user_id": row[6],
            "result_json": json.loads(row[7]) if row[7] else None,
            "kind": row[8],
        }

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
        """Append a new version, bump current_version, return the inserted version dict."""
        assert kind in ("apply", "rollback"), f"invalid kind: {kind}"
        version_id = _new_id("ver")
        now = time.time()
        async with aiosqlite.connect(self.path) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            async with db.execute(
                "SELECT COALESCE(MAX(version_n), 0) + 1 FROM deploy_versions WHERE deploy_id=?",
                (deploy_id,),
            ) as cur:
                row = await cur.fetchone()
                next_n = row[0]

            # resolve parent if not supplied: latest version of this deploy
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
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `cd control-plane && python -m pytest tests/unit/test_storage_deploys.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add control-plane/app/storage_deploys.py control-plane/tests/unit/test_storage_deploys.py
git commit -m "feat(cp): add DeployRepository with create/get/list/delete + version chain"
```

---

## Task 3: DeployRepository — append_version + monotonic chain

**Files:**
- Modify: `control-plane/tests/unit/test_storage_deploys.py` (append)

- [ ] **Step 1: Append failing tests**

```python
@pytest.mark.asyncio
async def test_append_version_monotonic_per_deploy():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")
        await Storage(path).init()
        repo = DeployRepository(path)

        d = await repo.create("app", owner_user_id="singleuser")
        v1 = await repo.append_version(
            d["id"], yaml_text="yaml-v1", components_hash="h1",
            applied_by_user_id="singleuser", result_json={"ok": True},
        )
        v2 = await repo.append_version(
            d["id"], yaml_text="yaml-v2", components_hash="h2",
            applied_by_user_id="singleuser", result_json={"ok": True},
        )

        assert v1["version_n"] == 1
        assert v2["version_n"] == 2
        assert v1["parent_version_id"] is None
        assert v2["parent_version_id"] == v1["id"]

        refreshed = await repo.get(d["id"])
        assert refreshed["current_version"] == 2


@pytest.mark.asyncio
async def test_append_version_kind_rollback_links_to_explicit_parent():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")
        await Storage(path).init()
        repo = DeployRepository(path)

        d = await repo.create("app", owner_user_id="singleuser")
        v1 = await repo.append_version(
            d["id"], yaml_text="yaml-v1", components_hash="h1",
            applied_by_user_id="singleuser", result_json=None,
        )
        v2 = await repo.append_version(
            d["id"], yaml_text="yaml-v2", components_hash="h2",
            applied_by_user_id="singleuser", result_json=None,
        )
        # rollback to v1: new version v3 with kind='rollback' and parent=v1
        v3 = await repo.append_version(
            d["id"], yaml_text="yaml-v1", components_hash="h1",
            applied_by_user_id="singleuser", result_json=None,
            kind="rollback", parent_version_id=v1["id"],
        )

        assert v3["version_n"] == 3
        assert v3["kind"] == "rollback"
        assert v3["parent_version_id"] == v1["id"]

        versions = await repo.list_versions(d["id"])
        assert [v["version_n"] for v in versions] == [1, 2, 3]


@pytest.mark.asyncio
async def test_versions_isolated_between_deploys():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")
        await Storage(path).init()
        repo = DeployRepository(path)

        a = await repo.create("a", owner_user_id="singleuser")
        b = await repo.create("b", owner_user_id="singleuser")

        await repo.append_version(a["id"], yaml_text="y", components_hash="h",
                                  applied_by_user_id="singleuser", result_json=None)
        await repo.append_version(a["id"], yaml_text="y", components_hash="h",
                                  applied_by_user_id="singleuser", result_json=None)
        await repo.append_version(b["id"], yaml_text="y", components_hash="h",
                                  applied_by_user_id="singleuser", result_json=None)

        va = await repo.list_versions(a["id"])
        vb = await repo.list_versions(b["id"])
        assert [v["version_n"] for v in va] == [1, 2]
        assert [v["version_n"] for v in vb] == [1]
```

- [ ] **Step 2: Run tests, verify they pass (the logic was already written in Task 2)**

Run: `cd control-plane && python -m pytest tests/unit/test_storage_deploys.py -v`
Expected: all 7 tests PASS (3 new + 4 from before).

If any new test fails, it's a bug in the Task 2 implementation — fix inline then re-run.

- [ ] **Step 3: Commit**

```bash
git add control-plane/tests/unit/test_storage_deploys.py
git commit -m "test(cp): cover version-chain invariants on DeployRepository"
```

---

## Task 4: Components-hash helper (shared between repo and apply path)

**Files:**
- Create: `control-plane/app/config/hashing.py`
- Test: `control-plane/tests/unit/test_components_hash.py` (new)

**Why this task:** `deploy_versions.components_hash` should be a stable hash of the normalized set of rendered components, so that "applying the same spec twice" produces the same hash (i.e., noise-free "same state" detection). We centralize the computation so the apply path and the rollback path produce identical hashes for identical content.

- [ ] **Step 1: Write failing test**

Create `control-plane/tests/unit/test_components_hash.py`:

```python
from app.config.hashing import components_hash_from_rendered


def test_hash_is_stable_across_dict_order():
    a = {
        ("h1", "c1"): {"component_hash": "AAA", "run": {"type": "docker"}},
        ("h2", "c2"): {"component_hash": "BBB", "run": {"type": "docker"}},
    }
    b = {
        ("h2", "c2"): {"component_hash": "BBB", "run": {"type": "docker"}},
        ("h1", "c1"): {"component_hash": "AAA", "run": {"type": "docker"}},
    }
    assert components_hash_from_rendered(a) == components_hash_from_rendered(b)


def test_hash_changes_when_component_hash_changes():
    a = {("h1", "c1"): {"component_hash": "AAA"}}
    b = {("h1", "c1"): {"component_hash": "ZZZ"}}
    assert components_hash_from_rendered(a) != components_hash_from_rendered(b)


def test_hash_changes_when_placement_changes():
    a = {("h1", "c1"): {"component_hash": "AAA"}}
    b = {("h2", "c1"): {"component_hash": "AAA"}}
    assert components_hash_from_rendered(a) != components_hash_from_rendered(b)


def test_empty_rendered_produces_stable_hash():
    h1 = components_hash_from_rendered({})
    h2 = components_hash_from_rendered({})
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex
```

- [ ] **Step 2: Run, verify fail**

Run: `cd control-plane && python -m pytest tests/unit/test_components_hash.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Create `control-plane/app/config/hashing.py`**

```python
"""Stable component-set hashing for deploy versioning."""
from __future__ import annotations

import hashlib
import json
from typing import Any


def components_hash_from_rendered(rendered: dict[tuple[str, str], dict[str, Any]]) -> str:
    """SHA256 over the sorted sequence of (host, component, component_hash).

    We include only (host, component_id, component_hash) so the hash is stable
    against non-material payload fields. `component_hash` is the per-component
    hash computed by the renderer (already includes config_archives content).
    """
    items = sorted(
        (host, cid, (payload or {}).get("component_hash", ""))
        for (host, cid), payload in rendered.items()
    )
    payload = json.dumps(items, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run, verify pass**

Run: `cd control-plane && python -m pytest tests/unit/test_components_hash.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add control-plane/app/config/hashing.py control-plane/tests/unit/test_components_hash.py
git commit -m "feat(cp): add stable components_hash for deploy versioning"
```

---

## Task 5: Legacy config row migration

**Files:**
- Create: `control-plane/app/storage_migrate.py`
- Modify: `control-plane/app/storage.py` — call migration from `init()`
- Create: `control-plane/tests/unit/test_storage_migrate.py`

- [ ] **Step 1: Write failing test**

Create `control-plane/tests/unit/test_storage_migrate.py`:

```python
import os
import tempfile
import time
import pytest
import aiosqlite

from app.storage import Storage
from app.storage_deploys import DeployRepository


_LEGACY_YAML = """api_version: maestro/v1
project: legacy-app
hosts:
  h1: {type: linux, address: 1.2.3.4}
components:
  c1:
    source: {type: docker, image: nginx}
    run: {type: docker}
deployment:
  - host: h1
    components: [c1]
"""


@pytest.mark.asyncio
async def test_init_migrates_legacy_config_into_default_deploy():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")

        # Simulate a pre-M1 DB: init then write legacy config row
        s = Storage(path)
        await s.init()
        await s.save_config("legacy-app", _LEGACY_YAML)

        # Drop all new-schema rows to simulate an upgrade-in-place
        async with aiosqlite.connect(path) as db:
            await db.execute("DELETE FROM deploy_versions;")
            await db.execute("DELETE FROM deploys;")
            await db.commit()

        # Re-run init: migration must recreate the default deploy from legacy config
        await Storage(path).init()

        repo = DeployRepository(path)
        default = await repo.get_by_name("singleuser", "default")
        assert default is not None
        assert default["owner_user_id"] == "singleuser"
        assert default["current_version"] == 1

        versions = await repo.list_versions(default["id"])
        assert len(versions) == 1
        assert versions[0]["yaml_text"] == _LEGACY_YAML
        assert versions[0]["kind"] == "apply"


@pytest.mark.asyncio
async def test_init_is_idempotent_no_double_migration():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")
        s = Storage(path)
        await s.init()
        await s.save_config("legacy-app", _LEGACY_YAML)
        await Storage(path).init()  # migrates
        await Storage(path).init()  # should not create a second version

        repo = DeployRepository(path)
        default = await repo.get_by_name("singleuser", "default")
        assert default is not None
        versions = await repo.list_versions(default["id"])
        assert len(versions) == 1  # still exactly one


@pytest.mark.asyncio
async def test_init_no_legacy_config_does_not_create_default():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")
        await Storage(path).init()
        repo = DeployRepository(path)
        default = await repo.get_by_name("singleuser", "default")
        assert default is None
```

- [ ] **Step 2: Run, verify fail**

Run: `cd control-plane && python -m pytest tests/unit/test_storage_migrate.py -v`
Expected: FAIL — migration not implemented.

- [ ] **Step 3: Create `control-plane/app/storage_migrate.py`**

```python
"""One-time migration from pre-M1 single-config-row to multi-deploy schema."""
from __future__ import annotations

import aiosqlite


async def migrate_legacy_config_to_default_deploy(db_path: str) -> None:
    """If a legacy `config` row exists and no `default` deploy has been created
    yet, materialize the legacy YAML as deploy 'default' owned by 'singleuser'.

    Idempotent: running multiple times has no effect after the first run.
    """
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON;")

        # Has a 'default' deploy already? (idempotency check)
        async with db.execute(
            "SELECT id FROM deploys WHERE owner_user_id=? AND name=?",
            ("singleuser", "default"),
        ) as cur:
            if await cur.fetchone() is not None:
                return

        # Read the legacy row
        async with db.execute(
            "SELECT project, yaml_text, applied_at FROM config WHERE id=1"
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return  # nothing to migrate

        _project, yaml_text, applied_at = row

    # Use repo from here on for consistent ID generation + writes
    # (deferred import to avoid a storage <-> repo cycle on module load)
    from .storage_deploys import DeployRepository
    from .config.hashing import components_hash_from_rendered

    repo = DeployRepository(db_path)
    d = await repo.create("default", owner_user_id="singleuser")
    await repo.append_version(
        d["id"],
        yaml_text=yaml_text,
        # We hash an empty rendered set: we can't render without an Engine+Hub,
        # and this is a migration artifact, not a canonical apply. Subsequent
        # applies will replace with the real components_hash.
        components_hash=components_hash_from_rendered({}),
        applied_by_user_id="singleuser",
        result_json={"migrated_from_legacy_config": True, "applied_at": applied_at},
        kind="apply",
    )
```

- [ ] **Step 4: Wire migration into `Storage.init()`**

Modify `control-plane/app/storage.py`, `init` method:

```python
async def init(self) -> None:
    async with aiosqlite.connect(self.path) as db:
        await db.executescript(_SCHEMA)
        await db.executescript(_SEED_SINGLEUSER)
        await db.execute("PRAGMA foreign_keys = ON;")
        await db.commit()
    # Deferred import: migration uses DeployRepository which imports storage
    from .storage_migrate import migrate_legacy_config_to_default_deploy
    await migrate_legacy_config_to_default_deploy(self.path)
```

- [ ] **Step 5: Run tests, verify they pass**

Run: `cd control-plane && python -m pytest tests/unit/test_storage_migrate.py tests/unit/test_storage_deploys.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add control-plane/app/storage_migrate.py control-plane/app/storage.py control-plane/tests/unit/test_storage_migrate.py
git commit -m "feat(cp): migrate legacy config row into default deploy on init"
```

---

## Task 6: Cross-deploy conflict validator

**Files:**
- Create: `control-plane/app/config/cross_deploy_validator.py`
- Create: `control-plane/tests/unit/test_cross_deploy_validator.py`

- [ ] **Step 1: Write failing test**

Create `control-plane/tests/unit/test_cross_deploy_validator.py`:

```python
from app.config.cross_deploy_validator import (
    check_cross_deploy_conflicts,
    CrossDeployConflict,
)
from app.config.loader import parse_deployment


_BASE = """api_version: maestro/v1
project: base
hosts:
  h1: {type: linux, address: 1.2.3.4}
components:
  web:
    source: {type: docker, image: nginx}
    run:
      type: docker
      ports: ["80:80"]
deployment:
  - host: h1
    components: [web]
"""


_OTHER_SAME_ID = """api_version: maestro/v1
project: other
hosts:
  h1: {type: linux, address: 1.2.3.4}
components:
  web:
    source: {type: docker, image: httpd}
    run: {type: docker}
deployment:
  - host: h1
    components: [web]
"""


_OTHER_DIFF_ID_SAME_PORT = """api_version: maestro/v1
project: other
hosts:
  h1: {type: linux, address: 1.2.3.4}
components:
  api:
    source: {type: docker, image: httpd}
    run:
      type: docker
      ports: ["80:8080"]
deployment:
  - host: h1
    components: [api]
"""


_OTHER_DIFFERENT_HOST = """api_version: maestro/v1
project: other
hosts:
  h2: {type: linux, address: 5.6.7.8}
components:
  web:
    source: {type: docker, image: httpd}
    run: {type: docker}
deployment:
  - host: h2
    components: [web]
"""


def test_no_conflict_when_other_deploy_on_different_host():
    mine = parse_deployment(_BASE)
    others = {"other_id": parse_deployment(_OTHER_DIFFERENT_HOST)}
    conflicts = check_cross_deploy_conflicts(mine, others)
    assert conflicts == []


def test_component_id_collision_same_host():
    mine = parse_deployment(_BASE)
    others = {"other_id": parse_deployment(_OTHER_SAME_ID)}
    conflicts = check_cross_deploy_conflicts(mine, others)
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c.kind == "component_id_collision"
    assert c.host == "h1"
    assert c.component_id == "web"
    assert c.other_deploy_id == "other_id"


def test_host_port_collision_same_host():
    mine = parse_deployment(_BASE)
    others = {"other_id": parse_deployment(_OTHER_DIFF_ID_SAME_PORT)}
    conflicts = check_cross_deploy_conflicts(mine, others)
    assert len(conflicts) == 1
    c = conflicts[0]
    assert c.kind == "host_port_collision"
    assert c.host == "h1"
    assert c.host_port == 80


def test_self_overlap_is_ignored():
    """A deploy never conflicts with itself; its own id is excluded from the check."""
    mine = parse_deployment(_BASE)
    others = {}  # the caller must already exclude the current deploy
    assert check_cross_deploy_conflicts(mine, others) == []
```

- [ ] **Step 2: Run, verify fail**

Run: `cd control-plane && python -m pytest tests/unit/test_cross_deploy_validator.py -v`
Expected: FAIL.

- [ ] **Step 3: Create `control-plane/app/config/cross_deploy_validator.py`**

```python
"""Cross-deploy conflict checks run at apply-time over other deploys' current versions."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .schema import DeploymentSpec


@dataclass(frozen=True)
class CrossDeployConflict:
    kind: str  # 'component_id_collision' | 'host_port_collision'
    host: str
    component_id: str | None = None
    host_port: int | None = None
    other_deploy_id: str | None = None
    other_component_id: str | None = None
    message: str = ""


def _placements(spec: DeploymentSpec) -> list[tuple[str, str]]:
    """Yield (host, component_id) for every deployment binding."""
    out: list[tuple[str, str]] = []
    for bind in spec.deployment:
        for cid in bind.components:
            out.append((bind.host, cid))
    return out


def _host_ports_for_component(spec: DeploymentSpec, component_id: str) -> list[int]:
    comp = spec.components.get(component_id)
    if comp is None:
        return []
    run = comp.run
    ports = []
    raw_ports = getattr(run, "ports", None) or []
    for p in raw_ports:
        # Format: "HOST:CONTAINER" or "HOST" (int or str); we only care about the host side.
        s = str(p)
        host_side = s.split(":")[0] if ":" in s else s
        try:
            ports.append(int(host_side))
        except (TypeError, ValueError):
            continue
    return ports


def check_cross_deploy_conflicts(
    mine: DeploymentSpec,
    others: dict[str, DeploymentSpec],
) -> list[CrossDeployConflict]:
    """Return conflicts between `mine` and each spec in `others` (keyed by deploy_id).

    The caller is responsible for excluding the current deploy's id from `others`.
    """
    out: list[CrossDeployConflict] = []
    my_placements = set(_placements(mine))
    my_port_claims: dict[tuple[str, int], str] = {}  # (host, port) -> component_id
    for host, cid in my_placements:
        for p in _host_ports_for_component(mine, cid):
            my_port_claims[(host, p)] = cid

    for other_id, other in others.items():
        other_placements = _placements(other)
        # component_id collision on same host
        for host, cid in other_placements:
            if (host, cid) in my_placements:
                out.append(CrossDeployConflict(
                    kind="component_id_collision",
                    host=host, component_id=cid,
                    other_deploy_id=other_id, other_component_id=cid,
                    message=f"component '{cid}' on host '{host}' is already bound by deploy '{other_id}'",
                ))
        # host-port collision
        for host, cid in other_placements:
            for p in _host_ports_for_component(other, cid):
                if (host, p) in my_port_claims:
                    out.append(CrossDeployConflict(
                        kind="host_port_collision",
                        host=host, host_port=p,
                        component_id=my_port_claims[(host, p)],
                        other_deploy_id=other_id, other_component_id=cid,
                        message=(f"host port {p} on '{host}' claimed by component "
                                 f"'{cid}' in deploy '{other_id}'"),
                    ))
    return out
```

- [ ] **Step 4: Run, verify pass**

Run: `cd control-plane && python -m pytest tests/unit/test_cross_deploy_validator.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add control-plane/app/config/cross_deploy_validator.py control-plane/tests/unit/test_cross_deploy_validator.py
git commit -m "feat(cp): cross-deploy component-id and host-port conflict validator"
```

---

## Task 7: `/api/deploys` router — list + create + get + delete

**Files:**
- Create: `control-plane/app/api/deploys.py`
- Modify: `control-plane/app/main.py` — wire `app.state.deploy_repo` + include router
- Create: `control-plane/tests/unit/test_api_deploys.py`

- [ ] **Step 1: Write failing test**

Create `control-plane/tests/unit/test_api_deploys.py`:

```python
from pathlib import Path
import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from app.main import create_app

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures"


@pytest.fixture
def client(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("MAESTRO_DB", os.path.join(td, "t.db"))
        app = create_app()
        with TestClient(app) as c:
            yield c


def test_list_empty(client):
    r = client.get("/api/deploys")
    assert r.status_code == 200
    assert r.json() == {"deploys": []}


def test_create_list_get_delete_cycle(client):
    r = client.post("/api/deploys", json={"name": "webapp-prod"})
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["name"] == "webapp-prod"
    assert created["owner_user_id"] == "singleuser"
    assert created["current_version"] is None
    deploy_id = created["id"]

    r = client.get("/api/deploys")
    assert r.status_code == 200
    assert len(r.json()["deploys"]) == 1

    r = client.get(f"/api/deploys/{deploy_id}")
    assert r.status_code == 200
    assert r.json()["id"] == deploy_id
    assert r.json()["versions"] == []

    r = client.delete(f"/api/deploys/{deploy_id}")
    assert r.status_code == 204

    r = client.get(f"/api/deploys/{deploy_id}")
    assert r.status_code == 404


def test_create_duplicate_name_is_409(client):
    client.post("/api/deploys", json={"name": "x"})
    r = client.post("/api/deploys", json={"name": "x"})
    assert r.status_code == 409


def test_create_missing_name_is_400(client):
    r = client.post("/api/deploys", json={})
    assert r.status_code == 400
```

- [ ] **Step 2: Run, verify fail**

Run: `cd control-plane && python -m pytest tests/unit/test_api_deploys.py -v`
Expected: FAIL — route not mounted.

- [ ] **Step 3: Create `control-plane/app/api/deploys.py`**

```python
"""REST router for multi-deploy CRUD + versions + apply."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response

from ..storage_deploys import DeployRepository, DeployNotFound


router = APIRouter(prefix="/api/deploys")


def _repo(request: Request) -> DeployRepository:
    return request.app.state.deploy_repo


def _current_user_id(request: Request) -> str:
    """M1 stub: always resolve to the materialized singleuser row.
    M5 will replace this with middleware that reads the session cookie.
    """
    return "singleuser"


@router.get("")
async def list_deploys(request: Request):
    user = _current_user_id(request)
    repo = _repo(request)
    return {"deploys": await repo.list_for_owner(user)}


@router.post("", status_code=201)
async def create_deploy(request: Request):
    user = _current_user_id(request)
    body = await request.json() if (await request.body()) else {}
    name = body.get("name")
    if not name or not isinstance(name, str):
        raise HTTPException(status_code=400, detail="'name' is required and must be a string")
    repo = _repo(request)
    try:
        d = await repo.create(name, owner_user_id=user)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return JSONResponse(d, status_code=201)


@router.get("/{deploy_id}")
async def get_deploy(request: Request, deploy_id: str):
    repo = _repo(request)
    try:
        d = await repo.get(deploy_id)
    except DeployNotFound:
        raise HTTPException(status_code=404, detail="deploy not found")
    versions = await repo.list_versions(deploy_id)
    return {**d, "versions": versions}


@router.delete("/{deploy_id}", status_code=204)
async def delete_deploy(request: Request, deploy_id: str):
    repo = _repo(request)
    try:
        await repo.delete(deploy_id)
    except DeployNotFound:
        raise HTTPException(status_code=404, detail="deploy not found")
    return Response(status_code=204)
```

- [ ] **Step 4: Wire the router + state in `control-plane/app/main.py`**

Modify `lifespan` to also create the repo, and `create_app` to include the router.

Replace the imports block and lifespan in `main.py`:

```python
from .api.router import router as api_router
from .api.deploys import router as deploys_router
from .api.install import router as install_router
from .api.ui import router as ui_router
from .storage import Storage
from .storage_deploys import DeployRepository
from .ws.hub import Hub
from .orchestrator import Engine


async def lifespan(app: FastAPI):
    db_path = os.environ.get("MAESTRO_DB", "control-plane.db")
    storage = Storage(db_path)
    await storage.init()
    hub = Hub()
    engine = Engine(hub)
    app.state.storage = storage
    app.state.deploy_repo = DeployRepository(db_path)
    app.state.hub = hub
    app.state.engine = engine
    yield
```

And in `create_app`, after the existing `app.include_router(api_router)`, add:

```python
    app.include_router(deploys_router)
```

- [ ] **Step 5: Run tests, verify pass**

Run: `cd control-plane && python -m pytest tests/unit/test_api_deploys.py -v`
Expected: all 4 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add control-plane/app/api/deploys.py control-plane/app/main.py control-plane/tests/unit/test_api_deploys.py
git commit -m "feat(cp): /api/deploys list/create/get/delete CRUD"
```

---

## Task 8: `/api/deploys/{id}/apply` + version chain

**Files:**
- Modify: `control-plane/app/api/deploys.py` — add apply + validate + diff endpoints
- Modify: `control-plane/tests/unit/test_api_deploys.py` — append tests

- [ ] **Step 1: Append failing tests**

Append to `control-plane/tests/unit/test_api_deploys.py`:

```python
_YAML = (FIXTURES / "deployment-simple.yaml").read_text()


def test_apply_creates_version_when_dry_run_false_even_if_no_daemon(client):
    r = client.post("/api/deploys", json={"name": "app"})
    deploy_id = r.json()["id"]

    r = client.post(
        f"/api/deploys/{deploy_id}/apply",
        json={"yaml_text": _YAML},
    )
    # No daemon: engine returns ok=False but the version is recorded anyway
    # (audit trail: we record failed applies).
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["version_n"] == 1
    assert data["kind"] == "apply"

    r = client.get(f"/api/deploys/{deploy_id}")
    assert r.json()["current_version"] == 1
    assert len(r.json()["versions"]) == 1


def test_apply_dry_run_does_not_create_version(client):
    r = client.post("/api/deploys", json={"name": "app"})
    deploy_id = r.json()["id"]

    r = client.post(
        f"/api/deploys/{deploy_id}/apply?dry_run=true",
        json={"yaml_text": _YAML},
    )
    assert r.status_code == 200
    data = r.json()
    assert "diff" in data
    assert "version_n" not in data  # no version created

    r = client.get(f"/api/deploys/{deploy_id}")
    assert r.json()["current_version"] is None


def test_apply_to_unknown_deploy_is_404(client):
    r = client.post(
        "/api/deploys/does-not-exist/apply",
        json={"yaml_text": _YAML},
    )
    assert r.status_code == 404


def test_apply_invalid_yaml_is_400(client):
    r = client.post("/api/deploys", json={"name": "app"})
    deploy_id = r.json()["id"]
    r = client.post(f"/api/deploys/{deploy_id}/apply", json={"yaml_text": "this: is: not valid"})
    assert r.status_code == 400


def test_validate_on_deploy(client):
    r = client.post("/api/deploys", json={"name": "app"})
    deploy_id = r.json()["id"]
    r = client.post(f"/api/deploys/{deploy_id}/validate", json={"yaml_text": _YAML})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_diff_on_deploy(client):
    r = client.post("/api/deploys", json={"name": "app"})
    deploy_id = r.json()["id"]
    r = client.post(f"/api/deploys/{deploy_id}/diff", json={"yaml_text": _YAML})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert "diff" in r.json()
```

- [ ] **Step 2: Run tests, verify fail**

Run: `cd control-plane && python -m pytest tests/unit/test_api_deploys.py -v -k apply or validate or diff`
Expected: FAIL — endpoints missing.

- [ ] **Step 3: Extend `control-plane/app/api/deploys.py`**

Add these imports at the top:

```python
from ..config.loader import parse_deployment, LoaderError
from ..config.validator import validate as semantic_validate
from ..config.hashing import components_hash_from_rendered
from ..config.cross_deploy_validator import check_cross_deploy_conflicts
from ..orchestrator import Engine
```

Add a body-reading helper (copied from the legacy router to keep semantics identical; we'll DRY later):

```python
async def _read_apply_body(request: Request) -> tuple[str, dict[str, str], dict[str, str]]:
    import json as _json
    ct = (request.headers.get("content-type") or "").split(";")[0].strip()
    raw = await request.body()
    if ct == "application/json":
        try:
            data = _json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            raise HTTPException(status_code=400, detail="invalid JSON body")
        if not isinstance(data, dict) or "yaml_text" not in data:
            raise HTTPException(status_code=400, detail="JSON body must include 'yaml_text'")
        ts = data.get("template_store") or {}
        fs = data.get("files_store") or {}
        if not isinstance(ts, dict) or not isinstance(fs, dict):
            raise HTTPException(status_code=400, detail="template_store and files_store must be objects")
        for name, store in (("template_store", ts), ("files_store", fs)):
            for k, v in store.items():
                if not isinstance(v, str):
                    raise HTTPException(
                        status_code=400,
                        detail=f"{name} values must be strings, got {type(v).__name__} for key '{k}'",
                    )
        return str(data["yaml_text"]), dict(ts), dict(fs)
    return raw.decode("utf-8", errors="replace"), {}, {}
```

Add the three endpoints:

```python
@router.post("/{deploy_id}/validate")
async def validate_on_deploy(request: Request, deploy_id: str):
    repo = _repo(request)
    try:
        await repo.get(deploy_id)
    except DeployNotFound:
        raise HTTPException(status_code=404, detail="deploy not found")
    yaml_text, _, _ = await _read_apply_body(request)
    try:
        spec = parse_deployment(yaml_text)
    except LoaderError as e:
        raise HTTPException(status_code=400, detail=str(e))
    errs = semantic_validate(spec)
    if errs:
        raise HTTPException(status_code=400, detail=[e.to_dict() for e in errs])
    return {
        "ok": True,
        "project": spec.project,
        "hosts": list(spec.hosts.keys()),
        "components": list(spec.components.keys()),
    }


@router.post("/{deploy_id}/diff")
async def diff_on_deploy(request: Request, deploy_id: str):
    repo = _repo(request)
    try:
        await repo.get(deploy_id)
    except DeployNotFound:
        raise HTTPException(status_code=404, detail="deploy not found")
    yaml_text, template_store, files_store = await _read_apply_body(request)
    try:
        spec = parse_deployment(yaml_text)
    except LoaderError as e:
        raise HTTPException(status_code=400, detail=str(e))
    errs = semantic_validate(spec)
    if errs:
        raise HTTPException(status_code=400, detail=[e.to_dict() for e in errs])
    engine: Engine = request.app.state.engine
    d = await engine.diff(spec, template_store=template_store, files_store=files_store)
    return {"ok": True, "diff": d.to_dict()}


@router.post("/{deploy_id}/apply")
async def apply_on_deploy(request: Request, deploy_id: str):
    user = _current_user_id(request)
    repo = _repo(request)
    try:
        await repo.get(deploy_id)
    except DeployNotFound:
        raise HTTPException(status_code=404, detail="deploy not found")

    yaml_text, template_store, files_store = await _read_apply_body(request)
    dry_run = request.query_params.get("dry_run", "false").lower() == "true"
    try:
        spec = parse_deployment(yaml_text)
    except LoaderError as e:
        raise HTTPException(status_code=400, detail=str(e))
    errs = semantic_validate(spec)
    if errs:
        raise HTTPException(status_code=400, detail=[e.to_dict() for e in errs])

    # Cross-deploy conflict check: other deploys' current versions on shared hosts
    all_deploys = await repo.list_for_owner(user)
    others: dict[str, Any] = {}
    for other in all_deploys:
        if other["id"] == deploy_id or other["current_version"] is None:
            continue
        v = await repo.get_version(other["id"], other["current_version"])
        try:
            others[other["id"]] = parse_deployment(v["yaml_text"])
        except LoaderError:
            continue
    conflicts = check_cross_deploy_conflicts(spec, others)
    if conflicts:
        raise HTTPException(
            status_code=409,
            detail={"conflicts": [c.__dict__ for c in conflicts]},
        )

    engine: Engine = request.app.state.engine
    result = await engine.apply(
        spec, dry_run=dry_run,
        template_store=template_store, files_store=files_store,
    )

    if dry_run:
        return result.to_dict()

    rendered = engine.render_all(spec, template_store=template_store, files_store=files_store)
    ch = components_hash_from_rendered(rendered)
    version = await repo.append_version(
        deploy_id,
        yaml_text=yaml_text,
        components_hash=ch,
        applied_by_user_id=user,
        result_json=result.to_dict(),
        kind="apply",
    )
    return {
        **result.to_dict(),
        "version_n": version["version_n"],
        "version_id": version["id"],
        "kind": version["kind"],
    }
```

Also add a typing import at the top: `from typing import Any`.

- [ ] **Step 4: Run tests, verify pass**

Run: `cd control-plane && python -m pytest tests/unit/test_api_deploys.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add control-plane/app/api/deploys.py control-plane/tests/unit/test_api_deploys.py
git commit -m "feat(cp): /api/deploys/{id}/{validate,diff,apply} with cross-deploy conflict check"
```

---

## Task 9: Rollback endpoint

**Files:**
- Modify: `control-plane/app/api/deploys.py` — add `/rollback/{vN}`
- Modify: `control-plane/tests/unit/test_api_deploys.py` — append test

- [ ] **Step 1: Append failing test**

```python
def test_rollback_creates_new_version_pointing_at_target(client):
    r = client.post("/api/deploys", json={"name": "app"})
    deploy_id = r.json()["id"]

    # v1
    client.post(f"/api/deploys/{deploy_id}/apply", json={"yaml_text": _YAML})
    # v2 — same yaml, but we still get a new version because apply always appends
    client.post(f"/api/deploys/{deploy_id}/apply", json={"yaml_text": _YAML})

    r = client.post(f"/api/deploys/{deploy_id}/rollback/1")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["version_n"] == 3
    assert data["kind"] == "rollback"

    r = client.get(f"/api/deploys/{deploy_id}")
    versions = r.json()["versions"]
    v1 = next(v for v in versions if v["version_n"] == 1)
    v3 = next(v for v in versions if v["version_n"] == 3)
    assert v3["parent_version_id"] == v1["id"]
    assert v3["yaml_text"] == v1["yaml_text"]


def test_rollback_to_unknown_version_is_404(client):
    r = client.post("/api/deploys", json={"name": "app"})
    deploy_id = r.json()["id"]
    client.post(f"/api/deploys/{deploy_id}/apply", json={"yaml_text": _YAML})
    r = client.post(f"/api/deploys/{deploy_id}/rollback/99")
    assert r.status_code == 404
```

- [ ] **Step 2: Run, verify fail**

Run: `cd control-plane && python -m pytest tests/unit/test_api_deploys.py::test_rollback_creates_new_version_pointing_at_target -v`
Expected: FAIL.

- [ ] **Step 3: Add the endpoint to `control-plane/app/api/deploys.py`**

Add, alongside the other handlers (and `DeployVersionNotFound` to the import from `storage_deploys`):

```python
from ..storage_deploys import DeployRepository, DeployNotFound, DeployVersionNotFound


@router.post("/{deploy_id}/rollback/{version_n}")
async def rollback_to_version(request: Request, deploy_id: str, version_n: int):
    user = _current_user_id(request)
    repo = _repo(request)
    try:
        target = await repo.get_version(deploy_id, version_n)
    except DeployVersionNotFound:
        raise HTTPException(status_code=404, detail="version not found")

    try:
        spec = parse_deployment(target["yaml_text"])
    except LoaderError as e:
        raise HTTPException(status_code=400, detail=f"target version has invalid YAML: {e}")
    errs = semantic_validate(spec)
    if errs:
        raise HTTPException(status_code=400, detail=[e.to_dict() for e in errs])

    engine: Engine = request.app.state.engine
    result = await engine.apply(spec)
    rendered = engine.render_all(spec)
    ch = components_hash_from_rendered(rendered)
    version = await repo.append_version(
        deploy_id,
        yaml_text=target["yaml_text"],
        components_hash=ch,
        applied_by_user_id=user,
        result_json={**result.to_dict(), "rolled_back_to": version_n},
        kind="rollback",
        parent_version_id=target["id"],
    )
    return {
        **result.to_dict(),
        "version_n": version["version_n"],
        "version_id": version["id"],
        "kind": version["kind"],
    }
```

- [ ] **Step 4: Run tests, verify pass**

Run: `cd control-plane && python -m pytest tests/unit/test_api_deploys.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add control-plane/app/api/deploys.py control-plane/tests/unit/test_api_deploys.py
git commit -m "feat(cp): /api/deploys/{id}/rollback/{version_n}"
```

---

## Task 10: Retro-compat shim on `/api/config/*`

**Files:**
- Modify: `control-plane/app/api/router.py` — route `/api/config/apply` through `DeployRepository` when writing, keep YAML read via legacy path for now
- Create: `control-plane/tests/unit/test_api_config_shim.py`

**Goal:** the legacy endpoint continues to work. When `/api/config/apply` is called with no prior state, it materializes the `default` deploy and records apply as version 1. On subsequent calls it appends new versions on the `default` deploy.

- [ ] **Step 1: Write failing test**

Create `control-plane/tests/unit/test_api_config_shim.py`:

```python
from pathlib import Path
import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from app.main import create_app

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures"


@pytest.fixture
def client(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("MAESTRO_DB", os.path.join(td, "t.db"))
        app = create_app()
        with TestClient(app) as c:
            yield c


def test_config_apply_creates_default_deploy_with_version(client):
    body = (FIXTURES / "deployment-simple.yaml").read_text()
    r = client.post("/api/config/apply", content=body,
                    headers={"content-type": "text/yaml"})
    # Daemon absent, result.ok may be False, but endpoint returns 200
    assert r.status_code == 200

    # The default deploy must now exist with one version
    r = client.get("/api/deploys")
    deploys = r.json()["deploys"]
    default = next((d for d in deploys if d["name"] == "default"), None)
    assert default is not None
    assert default["current_version"] == 1


def test_config_apply_second_time_appends_version(client):
    body = (FIXTURES / "deployment-simple.yaml").read_text()
    client.post("/api/config/apply", content=body, headers={"content-type": "text/yaml"})
    client.post("/api/config/apply", content=body, headers={"content-type": "text/yaml"})

    r = client.get("/api/deploys")
    default = next(d for d in r.json()["deploys"] if d["name"] == "default")
    r = client.get(f"/api/deploys/{default['id']}")
    assert len(r.json()["versions"]) == 2


def test_config_get_returns_latest_default_version(client):
    body = (FIXTURES / "deployment-simple.yaml").read_text()
    client.post("/api/config/apply", content=body, headers={"content-type": "text/yaml"})
    r = client.get("/api/config")
    assert r.status_code == 200
    data = r.json()
    assert data["yaml_text"] is not None
    assert "web" in data["yaml_text"]
```

- [ ] **Step 2: Run, verify fail**

Run: `cd control-plane && python -m pytest tests/unit/test_api_config_shim.py -v`
Expected: FAIL — shim still writes only the legacy row.

- [ ] **Step 3: Modify `/api/config/apply` and `/api/config` in `control-plane/app/api/router.py`**

Import at the top:

```python
from ..config.hashing import components_hash_from_rendered
from ..storage_deploys import DeployRepository
```

Replace `post_apply`:

```python
@router.post("/config/apply")
async def post_apply(request: Request):
    yaml_text, template_store, files_store = await _read_apply_body(request)
    dry_run = request.query_params.get("dry_run", "false").lower() == "true"
    try:
        spec = parse_deployment(yaml_text)
    except LoaderError as e:
        raise HTTPException(status_code=400, detail=str(e))
    errs = semantic_validate(spec)
    if errs:
        raise HTTPException(status_code=400, detail=[e.to_dict() for e in errs])
    engine: Engine = request.app.state.engine
    storage = request.app.state.storage
    deploy_repo: DeployRepository = request.app.state.deploy_repo

    if not dry_run:
        await storage.save_config(spec.project, yaml_text)  # legacy row kept in sync

    result = await engine.apply(
        spec, dry_run=dry_run,
        template_store=template_store, files_store=files_store,
    )

    if not dry_run:
        await storage.record_deploy(spec.project, result.ok, result.to_dict())
        # Route through the default deploy in the new schema
        default = await deploy_repo.get_by_name("singleuser", "default")
        if default is None:
            default = await deploy_repo.create("default", owner_user_id="singleuser")
        rendered = engine.render_all(spec, template_store=template_store, files_store=files_store)
        ch = components_hash_from_rendered(rendered)
        await deploy_repo.append_version(
            default["id"],
            yaml_text=yaml_text,
            components_hash=ch,
            applied_by_user_id="singleuser",
            result_json=result.to_dict(),
            kind="apply",
        )
    return result.to_dict()
```

Replace `get_config`:

```python
@router.get("/config")
async def get_config(request: Request):
    deploy_repo: DeployRepository = request.app.state.deploy_repo
    default = await deploy_repo.get_by_name("singleuser", "default")
    if default is None or default["current_version"] is None:
        # Fall back to legacy row if migration has not seen a deploy yet
        storage = request.app.state.storage
        row = await storage.load_config()
        if row is None:
            return {"project": None, "yaml_text": None, "applied_at": None}
        return {"project": row[0], "yaml_text": row[1], "applied_at": row[2]}
    v = await deploy_repo.get_version(default["id"], default["current_version"])
    # Reuse parse_deployment to surface `project` cleanly
    try:
        spec = parse_deployment(v["yaml_text"])
        project = spec.project
    except LoaderError:
        project = None
    return {"project": project, "yaml_text": v["yaml_text"], "applied_at": v["applied_at"]}
```

- [ ] **Step 4: Run tests**

```
cd control-plane && python -m pytest tests/unit/test_api_config_shim.py tests/unit/test_api.py tests/unit/test_api_apply.py -v
```

Expected: all PASS (shim tests + legacy tests remain green).

- [ ] **Step 5: Commit**

```bash
git add control-plane/app/api/router.py control-plane/tests/unit/test_api_config_shim.py
git commit -m "feat(cp): /api/config/apply shims onto default deploy via DeployRepository"
```

---

## Task 11: MCP backwards-compatibility verification

**Scope note:** the MCP server delegates to `/api/config/*` today. Since Task 10 keeps that surface working (now backed by the `default` deploy), the MCP tools continue to function unchanged. This task **verifies** that invariant — it is intentionally non-mutating. Adding first-class `deploy_id` parameters to MCP tools is a follow-up (tracked as M1.1) and not part of M1 itself.

**Files:** none modified.

- [ ] **Step 1: Run the MCP integration test**

```
cd "/c/Users/navis/Documents/Claude/Projects/Remote Control Agent" && python -m pytest tests/e2e/test_mcp_integration.py -v
```

Expected: PASS with no code changes to `app/mcp/server.py`. If it fails, the shim in Task 10 broke an invariant — fix the shim, not the test.

- [ ] **Step 2: If the test suite doesn't cover a direct call, do a smoke call**

Run (from repo root, with the CP running locally on 8765 per Task 12):

```
python -c "from control_plane.app.mcp.server import HTTPClient; import asyncio; \
print(asyncio.run(HTTPClient('http://127.0.0.1:8765').get_state()))"
```

(adjust import if `HTTPClient` is defined differently; this is a diagnostic only and should not be committed)

Expected: returns the `/api/state` payload without error.

- [ ] **Step 3: No commit**

Nothing changed.

---

## Task 12: End-to-end smoke — full CP test suite + live health

**Files:** none new.

- [ ] **Step 1: Run the whole CP test suite**

```
cd "/c/Users/navis/Documents/Claude/Projects/Remote Control Agent/control-plane" && python -m pytest tests/unit/ -v
```

Expected: all PASS. Any failure is a regression — fix inline before continuing.

- [ ] **Step 2: Start the CP locally**

```
cd "/c/Users/navis/Documents/Claude/Projects/Remote Control Agent" && MAESTRO_DB=/tmp/m1-smoke.db control-plane/.venv/bin/python -m uvicorn app.main:app --app-dir control-plane --port 8765
```

(If `.venv` is not bootstrapped, skip this step and document.)

- [ ] **Step 3: Exercise via curl**

```
curl -sf http://127.0.0.1:8765/api/healthz
curl -sf -X POST http://127.0.0.1:8765/api/deploys -H 'content-type: application/json' -d '{"name":"smoke"}'
curl -sf http://127.0.0.1:8765/api/deploys
```

Expected: 200s, a deploy named `smoke` appears in the list with `current_version: null`.

- [ ] **Step 4: Stop the server and commit any final docs**

Stop uvicorn. If you added a smoke-test recipe to the README during the task, commit it:

```bash
git add -A
git commit -m "chore(cp): M1 smoke validation complete"
```

---

## Milestone Exit Criteria

All of the following must hold before declaring M1 done:

1. Full test suite green: `pytest control-plane/tests/unit/ -v` → 0 failures.
2. Running the CP against a fresh DB produces a `singleuser` row + `users`/`deploys`/`deploy_versions` tables.
3. Running the CP against a pre-M1 DB (with a legacy `config` row) auto-migrates it into a `default` deploy with one version.
4. `/api/deploys` full CRUD + apply + rollback usable via curl.
5. `/api/config/apply` (legacy) still works, writes both the legacy row and a new version on the `default` deploy.
6. The MCP server continues to work unchanged for existing callers.

Out of scope (punted to M2–M5 per vision doc): metrics collection, wizard backend, frontend SPA, real auth middleware.
