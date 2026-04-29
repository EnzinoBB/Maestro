# MCP API-Key Auth & Universal `/api/*` Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-user API keys generated from the dashboard so the MCP stdio server (and any other automation) can authenticate to the Control Plane; require authentication on every `/api/*` endpoint; deprecate `MAESTRO_SINGLE_USER_MODE`.

**Architecture:** A new `api_keys` SQLite table stores hashed per-user keys. `CurrentUserMiddleware` is rewritten to accept either a session cookie or `Authorization: Bearer mae_…`. A FastAPI `require_user` dependency is attached at router level to every `/api/*` router (with a small public allowlist). A new `/settings` screen in the web UI lets users manage their keys (one-time display, soft revoke). The MCP stdio server reads `MAESTRO_API_KEY` from its environment and injects it as a Bearer header. The legacy router's hardcoded `applied_by_user_id="singleuser"` is replaced with the real caller's id.

**Tech Stack:** Python 3.11 + FastAPI + Starlette + aiosqlite (CP), React 18 + TanStack Query + react-router (web UI), `httpx` (MCP client), PBKDF2-SHA256 via `app/auth/passwords.py`.

**Spec:** [docs/superpowers/specs/2026-04-28-mcp-api-key-auth-design.md](../specs/2026-04-28-mcp-api-key-auth-design.md)

---

## File Structure

### New backend files

- `control-plane/app/auth/api_keys_repo.py` — `ApiKeysRepository` (CRUD + lookup by prefix + last-used touch + count).
- `control-plane/app/auth/deps.py` — `require_user` FastAPI dependency + custom HTTPException handler producing the structured error body.
- `control-plane/app/api/api_keys.py` — REST router for `/api/auth/keys` (list / create / revoke).
- `control-plane/tests/unit/test_api_keys_repo.py`
- `control-plane/tests/unit/test_middleware_api_key.py`
- `control-plane/tests/unit/test_api_auth_keys.py`
- `control-plane/tests/unit/test_legacy_router_attribution.py`
- `control-plane/tests/unit/test_mcp_server_auth.py`

### New frontend files

- `web-ui/src/screens/settings.tsx` — settings screen with Account + API keys sections.
- `web-ui/src/components/ApiKeysSection.tsx` — list table + "Generate" button + lazy-loaded data.
- `web-ui/src/components/GenerateApiKeyDialog.tsx` — two-step modal (label input → one-time display).
- `web-ui/src/components/RevokeApiKeyDialog.tsx` — confirm dialog.

### Modified backend files

- `control-plane/app/storage.py` — add `api_keys` table to `_SCHEMA`.
- `control-plane/app/auth/middleware.py` — accept Bearer header; remove `is_single_user_mode()`.
- `control-plane/app/api/auth.py` — drop `single_user_mode` from `/me`; recompute `needs_setup`.
- `control-plane/app/api/router.py` — replace hardcoded `singleuser` audit; add `dependencies=[Depends(require_user)]`.
- `control-plane/app/api/deploys.py` — replace per-handler `_current_user_id(request)` with router-level dependency.
- `control-plane/app/api/nodes.py` — same.
- `control-plane/app/api/metrics.py` — same.
- `control-plane/app/api/wizard.py` — same.
- `control-plane/app/main.py` — register new router, register exception handler, drop `SINGLEUSER_ID` import where no longer needed.
- `control-plane/app/mcp/server.py` — read `MAESTRO_API_KEY`, inject `Authorization: Bearer`.
- `scripts/install-cp.sh` — remove `MAESTRO_SINGLE_USER_MODE` env var and `--single-user` flag.
- `README.md` — drop the single-user-mode section; add MCP setup snippet.
- Existing tests under `control-plane/tests/unit/test_api_auth.py`, `test_api_nodes.py`, `test_admin_daemon_enroll.py`, `test_user_management.py`, `test_api.py` — update fixtures that set `MAESTRO_SINGLE_USER_MODE`.

### Modified frontend files

- `web-ui/src/App.tsx` — add `/settings` route.
- `web-ui/src/hooks/useAuth.tsx` — drop the `"single-user"` status from the union type and `fetchMe`.
- `web-ui/src/components/UserMenuPopover.tsx` — drop the single-user branch and the `Change password` direct entry; add a `Settings` entry.
- `web-ui/src/shell.tsx` (if needed) — add a nav link for Settings (verify during the task).

---

## Phase 1 — Storage layer

### Task 1: Add `api_keys` table to schema

**Files:**
- Modify: `control-plane/app/storage.py` (extend `_SCHEMA`)
- Test: `control-plane/tests/unit/test_storage_deploys.py` (already exists; extend with one assertion) OR create a tiny new file. Pick: extend the existing.

- [ ] **Step 1: Write the failing test**

Add at the bottom of `control-plane/tests/unit/test_storage_deploys.py`:

```python
import aiosqlite
import os
import tempfile
import pytest
from app.storage import Storage


@pytest.mark.asyncio
async def test_api_keys_table_exists():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")
        s = Storage(path)
        await s.init()
        async with aiosqlite.connect(path) as db:
            async with db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='api_keys'"
            ) as cur:
                row = await cur.fetchone()
        assert row is not None, "api_keys table must be created by Storage.init()"
```

- [ ] **Step 2: Run test to verify it fails**

```
cd control-plane
pytest tests/unit/test_storage_deploys.py::test_api_keys_table_exists -v
```

Expected: FAIL — table does not exist.

- [ ] **Step 3: Add the table to `_SCHEMA`**

In `control-plane/app/storage.py`, append to the `_SCHEMA` string (before the closing `"""`):

```sql
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
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/unit/test_storage_deploys.py::test_api_keys_table_exists -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```
git add control-plane/app/storage.py control-plane/tests/unit/test_storage_deploys.py
git commit --author="EnzinoBB <genieenzino@gmail.com>" -m "feat(storage): add api_keys table to schema"
```

---

### Task 2: `ApiKeysRepository`

**Files:**
- Create: `control-plane/app/auth/api_keys_repo.py`
- Create: `control-plane/tests/unit/test_api_keys_repo.py`

- [ ] **Step 1: Write the failing tests**

Create `control-plane/tests/unit/test_api_keys_repo.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd control-plane
pytest tests/unit/test_api_keys_repo.py -v
```

Expected: ImportError (module doesn't exist).

- [ ] **Step 3: Implement the repository**

Create `control-plane/app/auth/api_keys_repo.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/unit/test_api_keys_repo.py -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```
git add control-plane/app/auth/api_keys_repo.py control-plane/tests/unit/test_api_keys_repo.py
git commit --author="EnzinoBB <genieenzino@gmail.com>" -m "feat(auth): ApiKeysRepository with CRUD + prefix lookup"
```

---

## Phase 2 — Auth middleware + dependency

### Task 3: Custom HTTPException handler with structured body

The middleware/gate raise `HTTPException(401, ...)` and `HTTPException(403, ...)`. By default FastAPI returns `{"detail": "..."}` which is inconsistent with the rest of the API (`{"ok": false, "error": {...}}`). Add a custom handler.

**Files:**
- Create: `control-plane/app/api/_errors.py`
- Modify: `control-plane/app/main.py` (register the handler)
- Test: `control-plane/tests/unit/test_api_auth.py` (extend with one assertion)

- [ ] **Step 1: Write the failing test**

Append to `control-plane/tests/unit/test_api_auth.py`:

```python
def test_401_returns_structured_error_body(client_multiuser):
    r = client_multiuser.get("/api/deploys")
    assert r.status_code == 401
    body = r.json()
    assert body == {
        "ok": False,
        "error": {"code": "unauthenticated", "message": "authentication required"},
    }
```

- [ ] **Step 2: Run the test**

```
cd control-plane
pytest tests/unit/test_api_auth.py::test_401_returns_structured_error_body -v
```

Expected: FAIL — body shape is `{"detail": "..."}` today.

- [ ] **Step 3: Implement the handler**

Create `control-plane/app/api/_errors.py`:

```python
"""Custom error response shape for HTTPException raised inside /api/*."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse


_CODE_BY_STATUS = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exc_handler(request: Request, exc: HTTPException):
        # Only reshape /api/* responses; leave the rest (static, healthz) alone.
        if not request.url.path.startswith("/api/"):
            return JSONResponse(
                status_code=exc.status_code, content={"detail": exc.detail},
            )
        code = _CODE_BY_STATUS.get(exc.status_code, "error")
        message = (
            exc.detail if isinstance(exc.detail, str)
            else "request failed"
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"ok": False, "error": {"code": code, "message": message}},
        )
```

- [ ] **Step 4: Wire it into `create_app`**

In `control-plane/app/main.py`, after `app = FastAPI(...)` and before any `add_middleware` / `include_router`:

```python
from .api._errors import install_error_handlers
...
def create_app() -> FastAPI:
    app = FastAPI(title="Maestro Control Plane", version="0.1.0", lifespan=lifespan)
    install_error_handlers(app)
    ...
```

- [ ] **Step 5: Update existing tests that asserted the old body shape**

Search for tests that check `r.json()["detail"]` or similar against `/api/*` 401/403/404 responses:

```
cd control-plane
grep -rn '"detail"' tests/unit/ | grep -v "\.pyc"
```

For each match under `tests/unit/`, update the assertion to the new shape:

```python
# was: assert r.json()["detail"] == "authentication required"
# now:
body = r.json()
assert body["ok"] is False
assert body["error"]["code"] == "unauthenticated"
```

For tests where the message text isn't critical, just assert `body["error"]["code"]`. Run the full unit suite to catch any further breakage:

```
pytest tests/unit/ -x
```

Fix any remaining mismatches inline.

- [ ] **Step 6: Commit**

```
git add control-plane/app/api/_errors.py control-plane/app/main.py control-plane/tests/
git commit --author="EnzinoBB <genieenzino@gmail.com>" -m "feat(api): structured {ok,error} body for /api/* HTTPException"
```

---

### Task 4: Rewrite `CurrentUserMiddleware` to support Bearer

**Files:**
- Modify: `control-plane/app/auth/middleware.py`
- Modify: `control-plane/app/main.py` (`api_keys_repo` on app.state, drop `SINGLEUSER_ID` import if unused after later tasks — leave for now)
- Create: `control-plane/tests/unit/test_middleware_api_key.py`
- Modify existing: `control-plane/app/storage_nodes.py` (no change here, just verifying we have access to the repo from middleware via app.state)

- [ ] **Step 1: Add the repo to app.state**

In `control-plane/app/main.py`, in the `lifespan` function near `app.state.users_repo = ...`:

```python
from .auth.api_keys_repo import ApiKeysRepository
...
app.state.users_repo = UsersRepository(db_path)
app.state.api_keys_repo = ApiKeysRepository(db_path)
```

- [ ] **Step 2: Write the failing tests**

Create `control-plane/tests/unit/test_middleware_api_key.py`:

```python
import os
import tempfile
import time
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.auth.passwords import hash_password


@pytest.fixture
def env(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("MAESTRO_DB", os.path.join(td, "t.db"))
        monkeypatch.setenv("MAESTRO_METRICS_RETENTION_INTERVAL_S", "3600")
        monkeypatch.setenv("MAESTRO_SINGLE_USER_MODE", "false")
        app = create_app()
        with TestClient(app) as c:
            # Seed an admin and an API key for them
            r = c.post(
                "/api/auth/setup-admin",
                json={"username": "alice", "password": "correct-horse"},
            )
            assert r.status_code == 200
            user_id = r.json()["id"]
            # Drop the cookie so subsequent requests are anonymous unless Bearer
            c.cookies.clear()
            # Insert a key directly via the repo
            import asyncio
            from app.auth.api_keys_repo import ApiKeysRepository
            repo = ApiKeysRepository(os.environ["MAESTRO_DB"])

            async def _seed():
                full_key = "mae_test12345abcdefghijklmnopqrstuvwxyz"  # 40+ chars
                prefix = full_key[:9]
                khash = hash_password(full_key)
                row = await repo.create(
                    user_id=user_id, label="test", prefix=prefix, key_hash=khash,
                )
                return full_key, row

            full_key, key_row = asyncio.run(_seed())
            yield {"client": c, "user_id": user_id,
                   "full_key": full_key, "key_id": key_row["id"]}


def test_anonymous_request_returns_401(env):
    c = env["client"]
    r = c.get("/api/deploys")
    assert r.status_code == 401


def test_valid_bearer_authenticates(env):
    c = env["client"]
    r = c.get("/api/deploys",
              headers={"Authorization": f"Bearer {env['full_key']}"})
    assert r.status_code == 200


def test_invalid_bearer_returns_401_and_does_not_fallback_to_cookie(env):
    c = env["client"]
    # Login the cookie back in
    c.post("/api/auth/login",
           json={"username": "alice", "password": "correct-horse"})
    # Send a bogus Bearer alongside the valid cookie:
    # the request must fail because Bearer-presence forces key-auth path.
    r = c.get("/api/deploys",
              headers={"Authorization": "Bearer mae_completely_bogus_xxx"})
    assert r.status_code == 401


def test_revoked_key_returns_401(env):
    c = env["client"]
    import asyncio
    from app.auth.api_keys_repo import ApiKeysRepository
    repo = ApiKeysRepository(os.environ["MAESTRO_DB"])
    asyncio.run(repo.revoke(env["key_id"], user_id=env["user_id"]))
    r = c.get("/api/deploys",
              headers={"Authorization": f"Bearer {env['full_key']}"})
    assert r.status_code == 401


def test_bearer_updates_last_used(env):
    c = env["client"]
    import asyncio
    from app.auth.api_keys_repo import ApiKeysRepository
    repo = ApiKeysRepository(os.environ["MAESTRO_DB"])
    before = asyncio.run(repo.get(env["key_id"]))
    assert before["last_used_at"] is None

    r = c.get("/api/deploys",
              headers={"Authorization": f"Bearer {env['full_key']}"})
    assert r.status_code == 200

    # last_used_at update is fire-and-forget; give the loop a tick
    import time as _t
    for _ in range(20):
        _t.sleep(0.05)
        after = asyncio.run(repo.get(env["key_id"]))
        if after["last_used_at"] is not None:
            break
    assert after["last_used_at"] is not None
```

- [ ] **Step 3: Run tests to verify they fail**

```
cd control-plane
pytest tests/unit/test_middleware_api_key.py -v
```

Expected: failures on every test except possibly `test_anonymous_request_returns_401` (depending on existing behaviour).

- [ ] **Step 4: Rewrite the middleware**

Replace the contents of `control-plane/app/auth/middleware.py`:

```python
"""Current-user resolver: reads either the session cookie or an
Authorization: Bearer mae_… API key, and populates request.state.user_id.

Bearer wins if present: a request that sends an Authorization header is
treated as a key-auth attempt and does NOT fall back to the cookie if the
key turns out to be invalid. This avoids confused-deputy issues with
stolen-but-revoked keys.
"""
from __future__ import annotations

import asyncio
import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .passwords import verify_password


SINGLEUSER_ID = "singleuser"

log = logging.getLogger("maestro.auth.middleware")


class CurrentUserMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request.state.user_id = await self._authenticate(request)
        return await call_next(request)

    async def _authenticate(self, request: Request) -> str | None:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            key = auth[7:].strip()
            return await self._verify_api_key(request, key)

        sess = request.scope.get("session") or {}
        uid = sess.get("user_id") if isinstance(sess, dict) else None
        return uid if isinstance(uid, str) else None

    async def _verify_api_key(self, request: Request, key: str) -> str | None:
        if not key.startswith("mae_") or len(key) < 12:
            return None
        prefix = key[:9]
        repo = getattr(request.app.state, "api_keys_repo", None)
        if repo is None:
            return None
        rows = await repo.list_active_by_prefix(prefix)
        for row in rows:
            if verify_password(key, row["key_hash"]):
                # Best-effort last-used update, fire-and-forget.
                asyncio.create_task(self._touch(repo, row["id"]))
                return row["user_id"]
        return None

    @staticmethod
    async def _touch(repo, key_id: str) -> None:
        try:
            await repo.touch_last_used(key_id)
        except Exception as e:  # noqa: BLE001 — never block requests
            log.warning("failed to update last_used_at for %s: %s", key_id, e)
```

- [ ] **Step 5: Run tests to verify they pass**

```
pytest tests/unit/test_middleware_api_key.py -v
```

Expected: all green.

- [ ] **Step 6: Run the full unit suite to catch regressions**

```
pytest tests/unit/ -x
```

Existing tests that relied on `MAESTRO_SINGLE_USER_MODE` to bypass auth will start failing. Do NOT fix them in this task — they will be repaired wholesale in Phase 5. Confirm the failures are limited to:

- `test_api_auth.py::test_me_single_user_default`
- `test_api_auth.py::test_deploys_api_works_without_login_in_single_user_mode`
- `test_api_auth.py::test_me_reports_needs_setup_false_in_single_user_mode`
- `test_api_nodes.py` cases that use `client_singleuser`
- Similar in `test_admin_daemon_enroll.py`

Other failures are bugs introduced here — investigate before continuing.

- [ ] **Step 7: Commit**

```
git add control-plane/app/auth/middleware.py control-plane/app/main.py control-plane/tests/unit/test_middleware_api_key.py
git commit --author="EnzinoBB <genieenzino@gmail.com>" -m "feat(auth): middleware accepts Authorization: Bearer mae_… API keys"
```

---

### Task 5: `require_user` dependency

**Files:**
- Create: `control-plane/app/auth/deps.py`
- Test: covered indirectly by Task 4 tests + Task 10 (router gating)

- [ ] **Step 1: Implement the dependency**

Create `control-plane/app/auth/deps.py`:

```python
"""FastAPI dependencies for authn/authz."""
from __future__ import annotations

from fastapi import HTTPException, Request

from .middleware import SINGLEUSER_ID


def require_user(request: Request) -> str:
    """Ensure the request is authenticated as a real (non-singleuser) account.

    Returns the caller's user_id. Raises:
      - 401 unauthenticated  → no valid session and no valid API key
      - 403 forbidden        → the request authenticated as 'singleuser' (a
                                system row that should never make API calls
                                under the new model)
    """
    uid = getattr(request.state, "user_id", None)
    if not uid:
        raise HTTPException(status_code=401, detail="authentication required")
    if uid == SINGLEUSER_ID:
        raise HTTPException(status_code=403,
                            detail="system account cannot make API calls")
    return uid
```

- [ ] **Step 2: Run the existing middleware tests to verify nothing regresses**

```
cd control-plane
pytest tests/unit/test_middleware_api_key.py -v
```

Expected: all green (this task adds a helper used by later tasks; no behaviour change yet).

- [ ] **Step 3: Commit**

```
git add control-plane/app/auth/deps.py
git commit --author="EnzinoBB <genieenzino@gmail.com>" -m "feat(auth): require_user FastAPI dependency"
```

---

## Phase 3 — REST endpoints for key management

### Task 6: `POST /api/auth/keys` — create a new key

**Files:**
- Create: `control-plane/app/api/api_keys.py`
- Modify: `control-plane/app/main.py` (include the router)
- Create: `control-plane/tests/unit/test_api_auth_keys.py`

- [ ] **Step 1: Write the failing test**

Create `control-plane/tests/unit/test_api_auth_keys.py`:

```python
import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("MAESTRO_DB", os.path.join(td, "t.db"))
        monkeypatch.setenv("MAESTRO_METRICS_RETENTION_INTERVAL_S", "3600")
        monkeypatch.setenv("MAESTRO_SINGLE_USER_MODE", "false")
        app = create_app()
        with TestClient(app) as c:
            r = c.post("/api/auth/setup-admin",
                       json={"username": "alice", "password": "correct-horse"})
            assert r.status_code == 200
            yield c


def test_post_keys_creates_and_returns_clear_key(client):
    r = client.post("/api/auth/keys", json={"label": "laptop"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["label"] == "laptop"
    assert body["key"].startswith("mae_")
    assert len(body["key"]) >= 40
    assert body["prefix"] == body["key"][:9]
    assert "warning" in body


def test_post_keys_rejects_empty_label(client):
    r = client.post("/api/auth/keys", json={"label": ""})
    assert r.status_code == 400


def test_post_keys_rejects_label_over_64_chars(client):
    r = client.post("/api/auth/keys", json={"label": "x" * 65})
    assert r.status_code == 400


def test_post_keys_rejects_duplicate_active_label(client):
    r = client.post("/api/auth/keys", json={"label": "laptop"})
    assert r.status_code == 201
    r = client.post("/api/auth/keys", json={"label": "laptop"})
    assert r.status_code == 409


def test_post_keys_enforces_max_active_keys(client):
    for i in range(10):
        r = client.post("/api/auth/keys", json={"label": f"k{i}"})
        assert r.status_code == 201, r.text
    r = client.post("/api/auth/keys", json={"label": "k10"})
    assert r.status_code == 409
    body = r.json()
    assert body["error"]["code"] == "conflict"


def test_post_keys_requires_auth(client):
    client.cookies.clear()
    r = client.post("/api/auth/keys", json={"label": "laptop"})
    assert r.status_code == 401
```

- [ ] **Step 2: Run the test**

```
cd control-plane
pytest tests/unit/test_api_auth_keys.py::test_post_keys_creates_and_returns_clear_key -v
```

Expected: FAIL (404) — endpoint not registered yet.

- [ ] **Step 3: Implement the router (POST only for this task)**

Create `control-plane/app/api/api_keys.py`:

```python
"""REST router for /api/auth/keys — per-user API key management."""
from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth.api_keys_repo import ApiKeysRepository
from ..auth.deps import require_user
from ..auth.passwords import hash_password


MAX_ACTIVE_KEYS_PER_USER = 10
LABEL_MAX_CHARS = 64
KEY_PREFIX_LEN = 9  # 'mae_' + 5 chars

router = APIRouter(prefix="/api/auth/keys",
                   dependencies=[Depends(require_user)])


def _repo(request: Request) -> ApiKeysRepository:
    return request.app.state.api_keys_repo


async def _read_json(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if not raw:
        return {}
    import json as _json
    try:
        data = _json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body")
    return data if isinstance(data, dict) else {}


@router.post("", status_code=201)
async def post_create(request: Request, uid: str = Depends(require_user)):
    body = await _read_json(request)
    label = body.get("label")
    if not isinstance(label, str) or not label.strip():
        raise HTTPException(status_code=400, detail="'label' is required")
    label = label.strip()
    if len(label) > LABEL_MAX_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"'label' must be ≤{LABEL_MAX_CHARS} characters",
        )

    repo = _repo(request)
    if await repo.count_active_by_user(uid) >= MAX_ACTIVE_KEYS_PER_USER:
        raise HTTPException(
            status_code=409,
            detail=(f"max {MAX_ACTIVE_KEYS_PER_USER} active keys per user; "
                    "revoke an existing key first"),
        )

    full_key = f"mae_{secrets.token_urlsafe(32)}"
    prefix = full_key[:KEY_PREFIX_LEN]
    khash = hash_password(full_key)

    try:
        row = await repo.create(
            user_id=uid, label=label, prefix=prefix, key_hash=khash,
        )
    except ValueError:
        raise HTTPException(status_code=409,
                            detail=f"label '{label}' is already in use")

    return {
        "id": row["id"],
        "label": row["label"],
        "prefix": row["prefix"],
        "created_at": row["created_at"],
        "key": full_key,  # ← only time the cleartext is returned
        "warning": "Save this key now. You will not be able to see it again.",
    }
```

- [ ] **Step 4: Register the router in `main.py`**

In `control-plane/app/main.py`, near the other `from .api... import router as ...`:

```python
from .api.api_keys import router as api_keys_router
```

And in `create_app`, after `app.include_router(auth_router)`:

```python
app.include_router(api_keys_router)
```

- [ ] **Step 5: Run tests to verify they pass**

```
pytest tests/unit/test_api_auth_keys.py -v
```

Expected: all `test_post_*` tests green.

- [ ] **Step 6: Commit**

```
git add control-plane/app/api/api_keys.py control-plane/app/main.py control-plane/tests/unit/test_api_auth_keys.py
git commit --author="EnzinoBB <genieenzino@gmail.com>" -m "feat(api): POST /api/auth/keys to create per-user API keys"
```

---

### Task 7: `GET /api/auth/keys` — list own keys

**Files:**
- Modify: `control-plane/app/api/api_keys.py`
- Modify: `control-plane/tests/unit/test_api_auth_keys.py`

- [ ] **Step 1: Append failing tests**

Append to `control-plane/tests/unit/test_api_auth_keys.py`:

```python
def test_get_keys_returns_own_keys_only(client):
    client.post("/api/auth/keys", json={"label": "a"})
    client.post("/api/auth/keys", json={"label": "b"})

    r = client.get("/api/auth/keys")
    assert r.status_code == 200
    body = r.json()
    labels = sorted(k["label"] for k in body["keys"])
    assert labels == ["a", "b"]
    # Cleartext key MUST NOT appear in list
    for k in body["keys"]:
        assert "key" not in k
        assert "key_hash" not in k


def test_get_keys_includes_revoked(client):
    r = client.post("/api/auth/keys", json={"label": "a"})
    kid = r.json()["id"]
    client.delete(f"/api/auth/keys/{kid}")

    r = client.get("/api/auth/keys")
    keys = r.json()["keys"]
    assert len(keys) == 1
    assert keys[0]["revoked_at"] is not None


def test_get_keys_requires_auth(client):
    client.cookies.clear()
    r = client.get("/api/auth/keys")
    assert r.status_code == 401
```

- [ ] **Step 2: Run the new tests**

```
cd control-plane
pytest tests/unit/test_api_auth_keys.py::test_get_keys_returns_own_keys_only -v
```

Expected: FAIL (endpoint not implemented).

- [ ] **Step 3: Add the GET handler**

Append to `control-plane/app/api/api_keys.py`:

```python
@router.get("")
async def get_list(request: Request, uid: str = Depends(require_user)):
    rows = await _repo(request).list_by_user(uid)
    return {
        "keys": [
            {
                "id": r["id"],
                "label": r["label"],
                "prefix": r["prefix"],
                "created_at": r["created_at"],
                "last_used_at": r["last_used_at"],
                "revoked_at": r["revoked_at"],
            }
            for r in rows
        ]
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/unit/test_api_auth_keys.py -v
```

Expected: all green so far.

- [ ] **Step 5: Commit**

```
git add control-plane/app/api/api_keys.py control-plane/tests/unit/test_api_auth_keys.py
git commit --author="EnzinoBB <genieenzino@gmail.com>" -m "feat(api): GET /api/auth/keys lists caller's keys"
```

---

### Task 8: `DELETE /api/auth/keys/{key_id}` — revoke

**Files:**
- Modify: `control-plane/app/api/api_keys.py`
- Modify: `control-plane/tests/unit/test_api_auth_keys.py`

- [ ] **Step 1: Append failing tests**

Append to `control-plane/tests/unit/test_api_auth_keys.py`:

```python
def test_delete_revokes_key(client):
    r = client.post("/api/auth/keys", json={"label": "x"})
    kid = r.json()["id"]
    full_key = r.json()["key"]

    r = client.delete(f"/api/auth/keys/{kid}")
    assert r.status_code == 204

    # The revoked key no longer authenticates
    client.cookies.clear()
    r = client.get("/api/deploys",
                   headers={"Authorization": f"Bearer {full_key}"})
    assert r.status_code == 401


def test_delete_is_idempotent(client):
    r = client.post("/api/auth/keys", json={"label": "x"})
    kid = r.json()["id"]
    assert client.delete(f"/api/auth/keys/{kid}").status_code == 204
    assert client.delete(f"/api/auth/keys/{kid}").status_code == 204


def test_delete_other_users_key_returns_404(client, monkeypatch):
    # Create a second user and a key owned by them.
    # Easiest: hit the repo directly.
    import asyncio
    from app.auth.api_keys_repo import ApiKeysRepository
    from app.auth.passwords import hash_password
    repo = ApiKeysRepository(os.environ["MAESTRO_DB"])
    # Seed bob via direct SQL
    import aiosqlite
    import time as _t

    async def _seed():
        async with aiosqlite.connect(os.environ["MAESTRO_DB"]) as db:
            await db.execute(
                "INSERT INTO users (id, username, is_admin, created_at) "
                "VALUES (?,?,?,?)",
                ("usr_bob", "bob", 0, _t.time()),
            )
            await db.commit()
        return await repo.create(user_id="usr_bob", label="bobs",
                                 prefix="mae_bob01", key_hash=hash_password("mae_bob01xxxx"))

    bobs_key = asyncio.run(_seed())

    # alice (the test client) tries to revoke bob's key
    r = client.delete(f"/api/auth/keys/{bobs_key['id']}")
    assert r.status_code == 404


def test_delete_requires_auth(client):
    client.cookies.clear()
    r = client.delete("/api/auth/keys/ak_nonexistent")
    assert r.status_code == 401
```

- [ ] **Step 2: Run the new tests**

```
cd control-plane
pytest tests/unit/test_api_auth_keys.py::test_delete_revokes_key -v
```

Expected: FAIL.

- [ ] **Step 3: Add the DELETE handler**

Append to `control-plane/app/api/api_keys.py`:

```python
from fastapi.responses import Response


@router.delete("/{key_id}", status_code=204)
async def delete_revoke(key_id: str, request: Request,
                        uid: str = Depends(require_user)):
    repo = _repo(request)
    # If the key belongs to a different user, do NOT reveal that — return 404.
    try:
        existing = await repo.get(key_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="not found")
    if existing["user_id"] != uid:
        raise HTTPException(status_code=404, detail="not found")
    await repo.revoke(key_id, user_id=uid)
    return Response(status_code=204)
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/unit/test_api_auth_keys.py -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```
git add control-plane/app/api/api_keys.py control-plane/tests/unit/test_api_auth_keys.py
git commit --author="EnzinoBB <genieenzino@gmail.com>" -m "feat(api): DELETE /api/auth/keys/{id} soft-revokes the key"
```

---

### Task 9: Audit events on create / revoke

**Files:**
- Modify: `control-plane/app/api/api_keys.py`
- Modify: `control-plane/tests/unit/test_api_auth_keys.py`

The existing `metric_events` table accepts arbitrary `kind` strings. We write `api_key.created` and `api_key.revoked` rows on POST/DELETE.

- [ ] **Step 1: Add failing test**

Append to `control-plane/tests/unit/test_api_auth_keys.py`:

```python
def test_audit_event_emitted_on_create_and_revoke(client):
    import asyncio
    import aiosqlite
    import json as _json

    r = client.post("/api/auth/keys", json={"label": "audited"})
    kid = r.json()["id"]
    client.delete(f"/api/auth/keys/{kid}")

    async def _events():
        async with aiosqlite.connect(os.environ["MAESTRO_DB"]) as db:
            async with db.execute(
                "SELECT kind, payload_json FROM metric_events "
                "WHERE kind IN ('api_key.created', 'api_key.revoked') "
                "ORDER BY ts ASC"
            ) as cur:
                return await cur.fetchall()

    rows = asyncio.run(_events())
    kinds = [r[0] for r in rows]
    assert kinds == ["api_key.created", "api_key.revoked"]
    payload = _json.loads(rows[0][1])
    assert payload["key_id"] == kid
    assert payload["label"] == "audited"
```

- [ ] **Step 2: Run the test**

```
cd control-plane
pytest tests/unit/test_api_auth_keys.py::test_audit_event_emitted_on_create_and_revoke -v
```

Expected: FAIL.

- [ ] **Step 3: Implement audit emission**

Add this helper at the top of `control-plane/app/api/api_keys.py` (`Storage.path` is the DB path — verified at `app/storage.py:131`):

```python
async def _audit(request: Request, kind: str, scope_id: str, payload: dict) -> None:
    import aiosqlite, time as _t, json as _json
    db_path = request.app.state.storage.path
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO metric_events (ts, kind, scope, scope_id, payload_json) "
            "VALUES (?,?,?,?,?)",
            (_t.time(), kind, "user", scope_id, _json.dumps(payload)),
        )
        await db.commit()
```

In `control-plane/app/api/api_keys.py`, call this helper after a successful create and after a successful revoke:

```python
# inside post_create, just before `return {...}`:
await _audit(request, "api_key.created", uid,
             {"key_id": row["id"], "label": row["label"]})

# inside delete_revoke, just before `return Response(...)`:
await _audit(request, "api_key.revoked", uid,
             {"key_id": key_id, "label": existing["label"]})
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/unit/test_api_auth_keys.py -v
```

Expected: all green.

- [ ] **Step 5: Commit**

```
git add control-plane/app/api/api_keys.py control-plane/tests/unit/test_api_auth_keys.py
git commit --author="EnzinoBB <genieenzino@gmail.com>" -m "feat(api): emit api_key.created/revoked audit events"
```

---

## Phase 4 — Apply `require_user` everywhere + fix audit attribution

### Task 10: Gate the legacy router with `require_user`

The legacy `app/api/router.py` (paths like `/api/state`, `/api/config/apply`, `/api/components/{id}/start`) currently has zero auth. Add the dependency at router level.

**Files:**
- Modify: `control-plane/app/api/router.py`
- Modify: `control-plane/tests/unit/test_api.py` (or a similar legacy test) — add a 401 assertion

- [ ] **Step 1: Find the legacy test file and add the failing assertion**

```
cd control-plane
ls tests/unit/test_api*.py
```

Append a new test to whichever file already exercises legacy `/api/state` (likely `test_api.py` or `test_api_apply.py`). Pick the one that already has a fixture parallel to `client_multiuser`. Add:

```python
def test_legacy_state_requires_auth_in_multiuser(client_multiuser):
    client_multiuser.cookies.clear()
    r = client_multiuser.get("/api/state")
    assert r.status_code == 401

def test_legacy_apply_requires_auth_in_multiuser(client_multiuser):
    client_multiuser.cookies.clear()
    r = client_multiuser.post("/api/config/apply", content="project: p\n",
                              headers={"content-type": "text/yaml"})
    assert r.status_code == 401
```

- [ ] **Step 2: Run the tests**

Expected: FAIL (200 OK today).

- [ ] **Step 3: Add `require_user` to the router**

In `control-plane/app/api/router.py`, find the `router = APIRouter(...)` declaration near the top and change it to:

```python
from fastapi import APIRouter, Depends, HTTPException, Request
from ..auth.deps import require_user

router = APIRouter(dependencies=[Depends(require_user)])
```

If the existing import line is `from fastapi import APIRouter, ...` adapt it to include `Depends`.

- [ ] **Step 4: Run the tests**

Expected: PASS.

- [ ] **Step 5: Commit**

```
git add control-plane/app/api/router.py control-plane/tests/unit/test_api.py
git commit --author="EnzinoBB <genieenzino@gmail.com>" -m "feat(api): gate legacy /api/* router with require_user"
```

---

### Task 11: Convert per-handler auth checks to router-level dependency

`control-plane/app/api/deploys.py`, `nodes.py`, `metrics.py`, and `wizard.py` currently call `_current_user_id(request)` inline at the top of each protected handler. Promote it to router-level for consistency and to make sure no future handler accidentally skips the check.

Note: this is a refactor with **no behavioural change** outside the legacy router (the dependency was already enforced inside each handler). Tests should stay green throughout.

**Files:**
- Modify: `control-plane/app/api/deploys.py`
- Modify: `control-plane/app/api/nodes.py`
- Modify: `control-plane/app/api/metrics.py`
- Modify: `control-plane/app/api/wizard.py`
- Modify: `control-plane/app/api/install.py` (verify; if it has any `_current_user_id` calls, same change)

- [ ] **Step 1: Replace per-handler check in `deploys.py`**

In `control-plane/app/api/deploys.py`:

1. Add the import: `from ..auth.deps import require_user`.
2. Add `Depends` to the existing `from fastapi import ...` line if not present.
3. Change the router declaration:

```python
# from:
router = APIRouter(prefix="/api/deploys")
# to:
router = APIRouter(prefix="/api/deploys", dependencies=[Depends(require_user)])
```

4. Replace each `uid = _current_user_id(request)` call inside handlers with a parameter `uid: str = Depends(require_user)`. Example:

```python
# was:
@router.get("")
async def list_deploys(request: Request):
    uid = _current_user_id(request)
    ...

# becomes:
@router.get("")
async def list_deploys(request: Request, uid: str = Depends(require_user)):
    ...
```

5. Once all handlers use the dependency, remove the now-unused `_current_user_id` helper from the file.

- [ ] **Step 2: Run the existing deploys tests**

```
cd control-plane
pytest tests/unit/test_api_deploys.py -v
```

Expected: green.

- [ ] **Step 3: Repeat the same change for `nodes.py`, `metrics.py`, `wizard.py`**

For each file: same pattern — router-level `dependencies=[Depends(require_user)]`, drop inline `_current_user_id` calls in favour of `uid: str = Depends(require_user)` parameters, remove the helper.

Note for `nodes.py`: it has a special endpoint `nodes.py:218` that rejects password reset on the `singleuser` row. Keep that explicit check; `require_user` already rejects `singleuser` callers, but that path is about the **target** of the reset, not the caller — leave it.

- [ ] **Step 4: Run the full unit suite**

```
pytest tests/unit/ -x
```

Expected: green except for the known `MAESTRO_SINGLE_USER_MODE` failures from Phase 2 (those are addressed in Phase 5).

- [ ] **Step 5: Commit**

```
git add control-plane/app/api/
git commit --author="EnzinoBB <genieenzino@gmail.com>" -m "refactor(api): hoist require_user to router-level dependency"
```

---

### Task 12: Fix `applied_by_user_id` hardcoding in legacy router

The legacy router writes `applied_by_user_id="singleuser"` regardless of caller. Use the real user.

**Files:**
- Modify: `control-plane/app/api/router.py`
- Create: `control-plane/tests/unit/test_legacy_router_attribution.py`

- [ ] **Step 1: Write the failing test**

Create `control-plane/tests/unit/test_legacy_router_attribution.py`:

```python
import os
import tempfile
import asyncio
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("MAESTRO_DB", os.path.join(td, "t.db"))
        monkeypatch.setenv("MAESTRO_METRICS_RETENTION_INTERVAL_S", "3600")
        monkeypatch.setenv("MAESTRO_SINGLE_USER_MODE", "false")
        app = create_app()
        with TestClient(app) as c:
            r = c.post("/api/auth/setup-admin",
                       json={"username": "alice", "password": "correct-horse"})
            assert r.status_code == 200
            yield c, r.json()["id"]


def test_legacy_apply_records_real_user_in_audit(client):
    c, alice_id = client
    yaml_text = "project: t\nhosts: {}\ncomponents: {}\ndeployment: []\n"
    r = c.post("/api/config/apply", content=yaml_text,
               headers={"content-type": "text/yaml"})
    assert r.status_code == 200, r.text

    # Inspect deploy_versions: the most recent row's applied_by_user_id
    # must be alice's id, not 'singleuser'.
    import aiosqlite

    async def _last_applied_by():
        async with aiosqlite.connect(os.environ["MAESTRO_DB"]) as db:
            async with db.execute(
                "SELECT applied_by_user_id FROM deploy_versions "
                "ORDER BY applied_at DESC LIMIT 1"
            ) as cur:
                row = await cur.fetchone()
                return row[0] if row else None

    assert asyncio.run(_last_applied_by()) == alice_id
```

- [ ] **Step 2: Run the test**

```
cd control-plane
pytest tests/unit/test_legacy_router_attribution.py -v
```

Expected: FAIL — current code writes "singleuser".

- [ ] **Step 3: Apply the fix**

In `control-plane/app/api/router.py`, find the `post_apply` handler. Change its signature to inject the user:

```python
@router.post("/config/apply")
async def post_apply(request: Request, uid: str = Depends(require_user)):
    ...
```

Then locate the `await deploy_repo.append_version(` call and change `applied_by_user_id="singleuser"` to `applied_by_user_id=uid`.

Leave the `get_by_name("singleuser", "default")` and `create("default", owner_user_id="singleuser")` calls unchanged — the legacy `default` deploy is still owned by the system row by design.

Repeat the same `applied_by_user_id` fix for any other handler in `router.py` that calls `append_version` (search the file).

- [ ] **Step 4: Run the test**

```
pytest tests/unit/test_legacy_router_attribution.py -v
```

Expected: PASS.

Run the full legacy router suite to make sure nothing broke:

```
pytest tests/unit/test_api.py tests/unit/test_api_apply.py tests/unit/test_api_config_shim.py -v
```

- [ ] **Step 5: Commit**

```
git add control-plane/app/api/router.py control-plane/tests/unit/test_legacy_router_attribution.py
git commit --author="EnzinoBB <genieenzino@gmail.com>" -m "fix(api): legacy /api/config/apply audits the real caller, not singleuser"
```

---

## Phase 5 — Deprecate `MAESTRO_SINGLE_USER_MODE`

### Task 13: Update `/api/auth/me` and remove flag from server-side code

**Files:**
- Modify: `control-plane/app/api/auth.py`
- Modify: `control-plane/app/auth/middleware.py` (delete `is_single_user_mode`)

- [ ] **Step 1: Drop `single_user_mode` from `/api/auth/me`**

In `control-plane/app/api/auth.py`, replace the `get_me` handler:

```python
@router.get("/me")
async def get_me(request: Request):
    users = _users(request)
    needs_setup = await users.count_non_singleuser() == 0

    uid = getattr(request.state, "user_id", None)
    if uid and uid != SINGLEUSER_ID:
        try:
            u = await users.get(uid)
            return {
                "authenticated": True,
                "needs_setup": needs_setup,
                "id": u["id"],
                "username": u["username"],
                "is_admin": u["is_admin"],
            }
        except UserNotFound:
            pass
    return {
        "authenticated": False,
        "needs_setup": needs_setup,
    }
```

Remove the `is_single_user_mode` import at the top of the file; replace `from ..auth.middleware import SINGLEUSER_ID, is_single_user_mode` with `from ..auth.middleware import SINGLEUSER_ID`.

- [ ] **Step 2: Delete `is_single_user_mode` from `middleware.py`**

If the function still exists in `control-plane/app/auth/middleware.py` after Task 4, delete it. Likewise drop any unused imports (`os`).

- [ ] **Step 3: Run the auth tests**

```
cd control-plane
pytest tests/unit/test_api_auth.py -v
```

Several tests will still be failing because they reference `single_user_mode` in assertions or rely on `client_singleuser`. Those are addressed in the next task.

- [ ] **Step 4: Commit**

```
git add control-plane/app/api/auth.py control-plane/app/auth/middleware.py
git commit --author="EnzinoBB <genieenzino@gmail.com>" -m "refactor(auth): drop single_user_mode from /me; auth always required"
```

---

### Task 14: Repair existing tests that referenced single-user mode

**Files:**
- Modify: `control-plane/tests/unit/test_api_auth.py`
- Modify: `control-plane/tests/unit/test_api_nodes.py`
- Modify: `control-plane/tests/unit/test_admin_daemon_enroll.py`
- Modify: `control-plane/tests/unit/test_user_management.py`
- Modify: any other test that uses a `client_singleuser` fixture or sets `MAESTRO_SINGLE_USER_MODE`

- [ ] **Step 1: Inventory the affected tests**

```
cd control-plane
grep -rln 'MAESTRO_SINGLE_USER_MODE\|client_singleuser\|single_user_mode\|"single-user"' tests/
```

- [ ] **Step 2: Apply the repair pattern to each file**

For each file in the inventory:

1. Delete the `client_singleuser` fixture entirely.
2. In the `client_multiuser` fixture, drop `monkeypatch.setenv("MAESTRO_SINGLE_USER_MODE", "false")` (the env var no longer has any effect, but cleaning up is cheap and avoids confusion). Rename the fixture to plain `client` if appropriate.
3. Delete tests that assert single-user-mode-specific behaviour:
   - `test_me_single_user_default`
   - `test_deploys_api_works_without_login_in_single_user_mode`
   - `test_me_reports_needs_setup_false_in_single_user_mode`
   - any test in `test_api_nodes.py` / `test_admin_daemon_enroll.py` that uses the deleted fixture.
4. In the surviving tests, remove `single_user_mode` keys from assertions (e.g. `assert body["single_user_mode"] is False` → delete the line).

- [ ] **Step 3: Run the full unit suite**

```
pytest tests/unit/ -x
```

Expected: all green.

- [ ] **Step 4: Commit**

```
git add control-plane/tests/
git commit --author="EnzinoBB <genieenzino@gmail.com>" -m "test: drop MAESTRO_SINGLE_USER_MODE references from suite"
```

---

### Task 15: Remove `MAESTRO_SINGLE_USER_MODE` from `install-cp.sh`

**Files:**
- Modify: `scripts/install-cp.sh`

- [ ] **Step 1: Edit the installer**

In `scripts/install-cp.sh`:

1. Remove the line `SINGLE_USER=""    # "1" → set MAESTRO_SINGLE_USER_MODE=true in compose env` (around line 39).
2. Remove the `--single-user`-related branches in the CLI argument parsing (search for `--single-user` and `SINGLE_USER`).
3. In the `cat > "$INSTALL_DIR/docker-compose.yml" <<EOF` block, delete the `MAESTRO_SINGLE_USER_MODE: "${single_user_env}"` line (around line 218) and the `local single_user_env=...` lines preceding it.
4. Remove the comment block at lines 22-23 referencing the flag in single-user mode.

- [ ] **Step 2: Sanity-check the generated compose**

If you have a sandbox to dry-run the installer against, run:

```
INSTALL_DIR=/tmp/maestro-test bash scripts/install-cp.sh --dry-run
cat /tmp/maestro-test/docker-compose.yml
```

(If `--dry-run` is not implemented, just inspect the generated file structure visually after a real run on a throwaway host.)

Confirm the compose file has no `MAESTRO_SINGLE_USER_MODE` reference.

- [ ] **Step 3: Commit**

```
git add scripts/install-cp.sh
git commit --author="EnzinoBB <genieenzino@gmail.com>" -m "chore(install): drop MAESTRO_SINGLE_USER_MODE from CP installer"
```

---

### Task 16: Update README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace the single-user-mode section**

In `README.md`, find lines 58-65 (the section that says "Open `http://<cp-host>:8000`. Because `MAESTRO_SINGLE_USER_MODE=false` …") and replace with:

```markdown
Open `http://<cp-host>:8000`. The first visit shows a "create admin" form
(no admin account exists yet). After creating the first admin you can log
in normally; subsequent users are added via the admin UI.

All `/api/*` endpoints require authentication: a session cookie (web UI) or
an `Authorization: Bearer mae_…` API key (MCP, automation). Generate keys
from **Settings → API keys** in the dashboard.
```

- [ ] **Step 2: Add a "Using the MCP server" section**

Add after the install/configuration section:

````markdown
## Using the MCP server

The Maestro MCP server lets Claude Code (and any other MCP-compatible client)
operate Maestro on your behalf. Each user generates their own API key from
**Settings → API keys** in the dashboard.

Configure your MCP client (e.g. `claude_desktop_config.json` for Claude
Desktop, or your IDE-specific MCP config):

```json
{
  "mcpServers": {
    "maestro": {
      "command": "python",
      "args": ["-m", "app.mcp.server", "--control-plane", "http://<cp-host>:8000"],
      "env": { "MAESTRO_API_KEY": "mae_…" }
    }
  }
}
```

The key inherits the same permissions as the user who generated it. Revoke
keys at any time from the dashboard; revocation takes effect immediately.
````

- [ ] **Step 3: Commit**

```
git add README.md
git commit --author="EnzinoBB <genieenzino@gmail.com>" -m "docs(readme): drop single-user-mode; document MCP API-key setup"
```

---

## Phase 6 — MCP server

### Task 17: Add `MAESTRO_API_KEY` support to the stdio MCP server

**Files:**
- Modify: `control-plane/app/mcp/server.py`
- Create: `control-plane/tests/unit/test_mcp_server_auth.py`

- [ ] **Step 1: Write the failing test**

Create `control-plane/tests/unit/test_mcp_server_auth.py`:

```python
import os

from app.mcp.server import _auth_headers


def test_auth_headers_includes_bearer_when_env_set(monkeypatch):
    monkeypatch.setenv("MAESTRO_API_KEY", "mae_test_xyz")
    assert _auth_headers() == {"Authorization": "Bearer mae_test_xyz"}


def test_auth_headers_empty_when_env_unset(monkeypatch):
    monkeypatch.delenv("MAESTRO_API_KEY", raising=False)
    assert _auth_headers() == {}


def test_auth_headers_empty_when_env_blank(monkeypatch):
    monkeypatch.setenv("MAESTRO_API_KEY", "")
    assert _auth_headers() == {}
```

- [ ] **Step 2: Run the tests**

```
cd control-plane
pytest tests/unit/test_mcp_server_auth.py -v
```

Expected: ImportError or all FAIL.

- [ ] **Step 3: Implement `_auth_headers` and use it**

In `control-plane/app/mcp/server.py`:

1. Add an `import os` at the top if not present.
2. Add the helper near the top of the module (after the docstring, before `_schema_yaml_only`):

```python
def _auth_headers() -> dict:
    key = os.environ.get("MAESTRO_API_KEY") or ""
    if not key:
        return {}
    return {"Authorization": f"Bearer {key}"}
```

3. Update `MCPClient._post`, `_post_yaml`, and `_get` to merge `_auth_headers()` into the outgoing headers:

```python
async def _post(self, path: str, json_body=None, params=None) -> dict:
    async with httpx.AsyncClient(timeout=300.0) as c:
        r = await c.post(self.base + path, json=json_body,
                         params=params or {}, headers=_auth_headers())
        try:
            return r.json()
        except Exception:
            return {"ok": False, "error": {"code": "http", "message": r.text}}

async def _post_yaml(self, path: str, yaml_text: str, params=None) -> dict:
    headers = {"content-type": "text/yaml", **_auth_headers()}
    async with httpx.AsyncClient(timeout=300.0) as c:
        r = await c.post(self.base + path, content=yaml_text,
                         headers=headers, params=params or {})
        try:
            return r.json()
        except Exception:
            return {"ok": False, "error": {"code": "http", "message": r.text}}

async def _get(self, path: str, params=None) -> dict:
    async with httpx.AsyncClient(timeout=60.0) as c:
        r = await c.get(self.base + path, params=params or {},
                        headers=_auth_headers())
        try:
            return r.json()
        except Exception:
            return {"ok": False, "error": {"code": "http", "message": r.text}}
```

- [ ] **Step 4: Run unit tests**

```
pytest tests/unit/test_mcp_server_auth.py -v
```

Expected: green.

- [ ] **Step 5: Manual smoke test (optional but recommended)**

If you have a CP running locally:

1. Generate a key via `POST /api/auth/keys` (or via UI once it's built).
2. Run `MAESTRO_API_KEY=mae_… python -m app.mcp.server --control-plane http://localhost:8000` and pipe a `tools/call` request via stdio. Confirm the CP receives an authenticated request.

If a manual smoke isn't feasible at this point, defer to the integration phase.

- [ ] **Step 6: Commit**

```
git add control-plane/app/mcp/server.py control-plane/tests/unit/test_mcp_server_auth.py
git commit --author="EnzinoBB <genieenzino@gmail.com>" -m "feat(mcp): forward MAESTRO_API_KEY as Authorization: Bearer to CP"
```

---

## Phase 7 — Web UI

### Task 18: Drop the `"single-user"` status from `useAuth`

**Files:**
- Modify: `web-ui/src/hooks/useAuth.tsx`

- [ ] **Step 1: Update the type and `fetchMe`**

In `web-ui/src/hooks/useAuth.tsx`:

1. Remove the `"single-user"` variant from `AuthState`:

```ts
export type AuthState =
  | { status: "loading" }
  | { status: "needs-setup" }
  | { status: "anonymous" }
  | { status: "authenticated"; id: string; username: string; is_admin: boolean };
```

2. Update `fetchMe`:

```ts
async function fetchMe(): Promise<AuthState> {
  const r = await fetch("/api/auth/me", { credentials: "same-origin" });
  if (!r.ok) return { status: "anonymous" };
  const body = await r.json();
  if (body.authenticated) {
    return {
      status: "authenticated",
      id: body.id,
      username: body.username,
      is_admin: !!body.is_admin,
    };
  }
  if (body.needs_setup) {
    return { status: "needs-setup" };
  }
  return { status: "anonymous" };
}
```

3. Update the `RequireAuth` guard in `web-ui/src/App.tsx` if it special-cases `"single-user"` — currently it only treats `"anonymous"` and `"needs-setup"` as logged-out, so no change needed; verify by inspection.

- [ ] **Step 2: Build and type-check the web UI**

```
cd web-ui
npm run build
```

Expected: clean (no TS errors). If errors surface, they will name the consumers of the deleted variant — fix each by removing the `"single-user"` branch.

- [ ] **Step 3: Commit**

```
git add web-ui/src/hooks/useAuth.tsx web-ui/src/App.tsx
git commit --author="EnzinoBB <genieenzino@gmail.com>" -m "refactor(ui): drop \"single-user\" status from useAuth"
```

---

### Task 19: Update `UserMenuPopover`

**Files:**
- Modify: `web-ui/src/components/UserMenuPopover.tsx`

- [ ] **Step 1: Remove the single-user branch and `Change password` shortcut**

In `web-ui/src/components/UserMenuPopover.tsx`:

1. Remove `isSingleUser` and the `state.status !== "authenticated" && state.status !== "single-user"` short-circuit. The popover now only renders when authenticated:

```tsx
if (state.status !== "authenticated") return null;
```

2. Remove all branches that conditionally hide menu items for single-user mode (e.g. the `Change password` / single-user-hint section). The component should no longer import `Mono` for that hint if it was only used there — clean up the import.

3. Replace the in-popover `Change password` button with a `Settings` link. Use `react-router`'s `Link` (or `useNavigate`):

```tsx
import { Link } from "react-router-dom";

// ...
<Link to="/settings" style={menuItemStyle} onClick={() => setOpen(false)}>
  <Icons.Settings />
  Settings
</Link>
```

If `Icons.Settings` does not exist, use whatever cog/gear icon the component library provides, or import from `lucide-react` (verify it's already a project dep — if not, just use a text label without icon).

4. Delete the `<ChangePasswordDialog>` usage from this file. The dialog component itself stays (it will be reused inside the new `/settings` screen).

- [ ] **Step 2: Build and visually verify**

```
cd web-ui
npm run build
npm run dev   # then click the user avatar in the topbar
```

Confirm: only authenticated state renders the popover; the menu shows `Settings`, `Switch user`, `Sign out`. No `Change password` direct entry.

- [ ] **Step 3: Commit**

```
git add web-ui/src/components/UserMenuPopover.tsx
git commit --author="EnzinoBB <genieenzino@gmail.com>" -m "refactor(ui): UserMenuPopover links to /settings; drops single-user mode"
```

---

### Task 20: New `/settings` screen with Account section

**Files:**
- Create: `web-ui/src/screens/settings.tsx`
- Modify: `web-ui/src/App.tsx`

- [ ] **Step 1: Create the settings screen with the Account section**

Create `web-ui/src/screens/settings.tsx`:

```tsx
import { useState } from "react";
import { useAuth } from "../hooks/useAuth";
import { ChangePasswordDialog } from "../components/ChangePasswordDialog";
import { ApiKeysSection } from "../components/ApiKeysSection";

export function SettingsScreen() {
  const { state } = useAuth();
  const [changing, setChanging] = useState(false);

  if (state.status !== "authenticated") return null;

  return (
    <div className="cp-page">
      <h1>Settings</h1>

      <section style={{ marginTop: 24 }}>
        <h2>Account</h2>
        <dl>
          <dt>Username</dt><dd>{state.username}</dd>
          <dt>Role</dt><dd>{state.is_admin ? "admin" : "operator"}</dd>
        </dl>
        <button onClick={() => setChanging(true)}>Change password</button>
        {changing && (
          <ChangePasswordDialog onClose={() => setChanging(false)} />
        )}
      </section>

      <section style={{ marginTop: 32 }}>
        <h2>API keys</h2>
        <ApiKeysSection />
      </section>
    </div>
  );
}
```

(Match the existing conventions for class names / spacing — peek at `screens/admin.tsx` for reference and adjust the JSX accordingly so the styling looks consistent.)

- [ ] **Step 2: Add the route**

In `web-ui/src/App.tsx`, add the import and the route inside the inner `<Routes>`:

```tsx
import { SettingsScreen } from "./screens/settings";

// ... inside the inner <Routes>:
<Route path="/settings" element={<SettingsScreen />} />
```

- [ ] **Step 3: Stub `ApiKeysSection` so the build passes**

Create `web-ui/src/components/ApiKeysSection.tsx` with a placeholder; Task 21 will fill it in:

```tsx
export function ApiKeysSection() {
  return <p>Loading…</p>;
}
```

- [ ] **Step 4: Build**

```
cd web-ui
npm run build
```

Expected: clean. Visit `/settings` in the running dev server; confirm the Account section renders and the placeholder is visible.

- [ ] **Step 5: Commit**

```
git add web-ui/src/screens/settings.tsx web-ui/src/components/ApiKeysSection.tsx web-ui/src/App.tsx
git commit --author="EnzinoBB <genieenzino@gmail.com>" -m "feat(ui): add /settings screen with Account section"
```

---

### Task 21: API keys list table

**Files:**
- Modify: `web-ui/src/components/ApiKeysSection.tsx`
- Create: `web-ui/src/components/GenerateApiKeyDialog.tsx` (stub for now)
- Create: `web-ui/src/components/RevokeApiKeyDialog.tsx` (stub for now)

- [ ] **Step 1: Stub the two dialogs so imports resolve**

Create `web-ui/src/components/GenerateApiKeyDialog.tsx`:

```tsx
export function GenerateApiKeyDialog({ onClose }: { onClose: () => void }) {
  return (
    <div className="cp-modal-backdrop">
      <div className="cp-modal">
        <p>(Generate dialog — implemented in next task)</p>
        <button onClick={onClose}>Close</button>
      </div>
    </div>
  );
}
```

Create `web-ui/src/components/RevokeApiKeyDialog.tsx`:

```tsx
export function RevokeApiKeyDialog({
  label, onConfirm, onClose,
}: { label: string; onConfirm: () => void; onClose: () => void }) {
  return (
    <div className="cp-modal-backdrop">
      <div className="cp-modal">
        <p>(Revoke '{label}' — implemented in next task)</p>
        <button onClick={onConfirm}>Confirm</button>
        <button onClick={onClose}>Cancel</button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Implement the list with TanStack Query**

Replace `web-ui/src/components/ApiKeysSection.tsx` with:

```tsx
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { GenerateApiKeyDialog } from "./GenerateApiKeyDialog";
import { RevokeApiKeyDialog } from "./RevokeApiKeyDialog";

type ApiKey = {
  id: string;
  label: string;
  prefix: string;
  created_at: number;
  last_used_at: number | null;
  revoked_at: number | null;
};

async function fetchKeys(): Promise<ApiKey[]> {
  const r = await fetch("/api/auth/keys", { credentials: "same-origin" });
  if (!r.ok) throw new Error(`failed to fetch keys (${r.status})`);
  const body = await r.json();
  return body.keys;
}

async function revokeKey(id: string): Promise<void> {
  const r = await fetch(`/api/auth/keys/${id}`, {
    method: "DELETE",
    credentials: "same-origin",
  });
  if (!r.ok && r.status !== 204) {
    throw new Error(`failed to revoke (${r.status})`);
  }
}

function relativeTime(ts: number | null): string {
  if (!ts) return "never";
  const diff = (Date.now() / 1000) - ts;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export function ApiKeysSection() {
  const qc = useQueryClient();
  const { data: keys = [], isLoading } = useQuery({
    queryKey: ["api-keys"], queryFn: fetchKeys,
  });
  const [generating, setGenerating] = useState(false);
  const [revoking, setRevoking] = useState<ApiKey | null>(null);

  const revokeMut = useMutation({
    mutationFn: revokeKey,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["api-keys"] }),
  });

  if (isLoading) return <p>Loading…</p>;

  return (
    <div>
      <p style={{ color: "var(--cp-muted, #888)", marginBottom: 12 }}>
        API keys allow external tools (like the Claude Code MCP server) to
        access Maestro on your behalf. Anyone with a key has the same
        permissions as you do — keep them secret.
      </p>

      <button onClick={() => setGenerating(true)}>Generate API key</button>

      {keys.length === 0 ? (
        <p style={{ marginTop: 16 }}>No API keys yet.</p>
      ) : (
        <table style={{ marginTop: 16, width: "100%" }}>
          <thead>
            <tr>
              <th>Label</th>
              <th>Prefix</th>
              <th>Created</th>
              <th>Last used</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {keys.map(k => (
              <tr key={k.id}>
                <td>{k.label}</td>
                <td><code>{k.prefix}…</code></td>
                <td>{relativeTime(k.created_at)}</td>
                <td>{relativeTime(k.last_used_at)}</td>
                <td>
                  {k.revoked_at == null
                    ? <span style={{ color: "green" }}>active</span>
                    : <span style={{ color: "#888" }}>revoked</span>}
                </td>
                <td>
                  {k.revoked_at == null && (
                    <button onClick={() => setRevoking(k)}>Revoke</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {generating && (
        <GenerateApiKeyDialog onClose={() => {
          setGenerating(false);
          qc.invalidateQueries({ queryKey: ["api-keys"] });
        }} />
      )}

      {revoking && (
        <RevokeApiKeyDialog
          label={revoking.label}
          onConfirm={async () => {
            await revokeMut.mutateAsync(revoking.id);
            setRevoking(null);
          }}
          onClose={() => setRevoking(null)}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 3: Build**

```
cd web-ui
npm run build && npm run dev
```

Visit `/settings`. Confirm the empty-state message renders. The Generate button opens the placeholder dialog (we'll fill it next).

- [ ] **Step 4: Commit**

```
git add web-ui/src/components/ApiKeysSection.tsx web-ui/src/components/GenerateApiKeyDialog.tsx web-ui/src/components/RevokeApiKeyDialog.tsx
git commit --author="EnzinoBB <genieenzino@gmail.com>" -m "feat(ui): API keys list with generate/revoke wiring"
```

---

### Task 22: Generate-key dialog (two-step flow with one-time display)

**Files:**
- Modify: `web-ui/src/components/GenerateApiKeyDialog.tsx`

- [ ] **Step 1: Implement the two-step flow**

Replace `web-ui/src/components/GenerateApiKeyDialog.tsx`:

```tsx
import { useState } from "react";

type CreatedKey = {
  id: string;
  label: string;
  prefix: string;
  key: string;
};

async function createKey(label: string): Promise<CreatedKey> {
  const r = await fetch("/api/auth/keys", {
    method: "POST",
    credentials: "same-origin",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ label }),
  });
  const body = await r.json();
  if (!r.ok) {
    const msg = body?.error?.message ?? `failed (${r.status})`;
    throw new Error(msg);
  }
  return body;
}

function configSnippet(cpUrl: string, key: string): string {
  return JSON.stringify({
    mcpServers: {
      maestro: {
        command: "python",
        args: ["-m", "app.mcp.server", "--control-plane", cpUrl],
        env: { MAESTRO_API_KEY: key },
      },
    },
  }, null, 2);
}

export function GenerateApiKeyDialog({ onClose }: { onClose: () => void }) {
  const [label, setLabel] = useState("");
  const [created, setCreated] = useState<CreatedKey | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setErr(null);
    setBusy(true);
    try {
      const k = await createKey(label.trim());
      setCreated(k);
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "failed");
    } finally {
      setBusy(false);
    }
  };

  const cpUrl = window.location.origin;
  const snippet = created ? configSnippet(cpUrl, created.key) : "";

  return (
    <div className="cp-modal-backdrop" onClick={(e) => e.stopPropagation()}>
      <div className="cp-modal" onClick={(e) => e.stopPropagation()}>
        {!created ? (
          <>
            <h3>Generate API key</h3>
            <label>
              Label
              <input
                autoFocus
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                maxLength={64}
                placeholder="e.g. claude-code-laptop"
              />
            </label>
            {err && <p style={{ color: "crimson" }}>{err}</p>}
            <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
              <button onClick={onClose}>Cancel</button>
              <button
                disabled={!label.trim() || busy}
                onClick={submit}
              >
                {busy ? "Generating…" : "Generate"}
              </button>
            </div>
          </>
        ) : (
          <>
            <h3>Save your API key</h3>
            <p style={{ background: "#fff7d6", padding: 8, borderRadius: 4 }}>
              <strong>Save this key now. You won't be able to see it again.</strong>
            </p>
            <input readOnly value={created.key} style={{ width: "100%" }} />
            <button onClick={() => navigator.clipboard.writeText(created.key)}>
              Copy key
            </button>

            <h4 style={{ marginTop: 16 }}>MCP client config</h4>
            <pre style={{ background: "#f5f5f5", padding: 8, overflowX: "auto" }}>
              {snippet}
            </pre>
            <button onClick={() => navigator.clipboard.writeText(snippet)}>
              Copy config
            </button>

            <div style={{ marginTop: 16 }}>
              <button onClick={onClose}>I've saved it, close</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
```

(If a `cp-modal` / `cp-modal-backdrop` style isn't already in `styles.css`, copy the pattern used by `ChangePasswordDialog`. Keep visual consistency.)

- [ ] **Step 2: Manual smoke test**

Run dev server, go to `/settings`, click `Generate API key`, give a label, generate, copy. The new key appears in the list after closing the dialog (the wrapper invalidates the query).

- [ ] **Step 3: Commit**

```
git add web-ui/src/components/GenerateApiKeyDialog.tsx
git commit --author="EnzinoBB <genieenzino@gmail.com>" -m "feat(ui): two-step Generate API key dialog with one-time display"
```

---

### Task 23: Revoke-key confirm dialog

**Files:**
- Modify: `web-ui/src/components/RevokeApiKeyDialog.tsx`

- [ ] **Step 1: Implement the confirm dialog**

Replace `web-ui/src/components/RevokeApiKeyDialog.tsx`:

```tsx
import { useState } from "react";

export function RevokeApiKeyDialog({
  label, onConfirm, onClose,
}: { label: string; onConfirm: () => Promise<void>; onClose: () => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const click = async () => {
    setBusy(true);
    setErr(null);
    try {
      await onConfirm();
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="cp-modal-backdrop">
      <div className="cp-modal">
        <h3>Revoke key</h3>
        <p>
          Revoke key <strong>'{label}'</strong>? Tools using this key will
          stop working immediately. This cannot be undone.
        </p>
        {err && <p style={{ color: "crimson" }}>{err}</p>}
        <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
          <button onClick={onClose} disabled={busy}>Cancel</button>
          <button
            onClick={click}
            disabled={busy}
            style={{ background: "crimson", color: "white" }}
          >
            {busy ? "Revoking…" : "Revoke"}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Manual smoke test**

Generate a key, then revoke it from the table. The row updates to `revoked` status; the actions column hides the Revoke button.

- [ ] **Step 3: Commit**

```
git add web-ui/src/components/RevokeApiKeyDialog.tsx
git commit --author="EnzinoBB <genieenzino@gmail.com>" -m "feat(ui): revoke-key confirm dialog"
```

---

## Phase 8 — End-to-end smoke (real infrastructure)

### Task 24: Test infrastructure preparation

The user has provided two production-like target machines for end-to-end verification. They share the same SSH credentials and both have `sudo` rights.

**Targets:**
- **Server 1** — `109.199.123.26` (currently running CP + Daemon + a `caddy:2-alpine` container that serves the Maestro public website from a `website/` directory)
- **Server 2** — `38.242.234.47` (currently running the Daemon only)

**SSH access (both):**
- User: `agent`
- Password: `Agent01.2026`

**Convention for the smoke test admin:** when reinstalling the CP from scratch, create the first admin via the UI form using:
- Username: `admin`
- Password: `Password01.2026`

This pair is reused across smoke tests so any tester can pick up the box.

- [ ] **Step 1: Connect to both servers and confirm sudo access**

```
ssh agent@109.199.123.26   # password: Agent01.2026
sudo -n true || sudo -v    # confirm sudo works
exit

ssh agent@38.242.234.47    # password: Agent01.2026
sudo -n true || sudo -v
exit
```

If either fails, stop and report — the user-facing smoke can't continue without sudo.

- [ ] **Step 2: Take a snapshot of the existing layout on Server 1**

Before reinstalling, capture what's currently running so the rollback is well-defined:

```
ssh agent@109.199.123.26
docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
ls -la /var/lib/maestro/ 2>/dev/null || echo "no /var/lib/maestro"
ls -la website/ 2>/dev/null || true
```

Note: confirm the `caddy:2-alpine` container name and the volume mount that backs the website (typically a bind mount from `~/website` or `/srv/website`). Record this in a scratchpad — Task 25 needs it.

- [ ] **Step 3: No code changes — proceed when both servers are reachable and snapshot recorded.**

---

### Task 25: Reinstall CP and Daemon from scratch on Server 1

This task confirms the installer scripts still work after the deprecation of `MAESTRO_SINGLE_USER_MODE` (Phase 5 changes).

- [ ] **Step 1: Stop and remove the existing CP install on Server 1**

```
ssh agent@109.199.123.26
cd /opt/maestro-cp 2>/dev/null && sudo docker compose down -v && cd /
sudo rm -rf /opt/maestro-cp /var/lib/maestro
```

(Adjust paths to match what was discovered in Task 24 Step 2 — those above are the conventional install paths; the actual installer may use different ones.)

- [ ] **Step 2: Stop and remove the existing daemon**

```
sudo systemctl stop maestro-daemon || true
sudo systemctl disable maestro-daemon || true
sudo rm -f /usr/local/bin/maestro-daemon /etc/systemd/system/maestro-daemon.service
sudo rm -rf /etc/maestro /var/lib/maestro-daemon
sudo systemctl daemon-reload
```

- [ ] **Step 3: Reinstall the CP from the local checkout**

From the dev box, push the freshly-built CP image / installer to the server (or use the project's `install-cp.sh` directly if it pulls from GitHub releases):

```
# from the dev box
scp scripts/install-cp.sh agent@109.199.123.26:/tmp/install-cp.sh

ssh agent@109.199.123.26 \
  'sudo bash /tmp/install-cp.sh --port 8000 --version <current-tag-or-main>'
```

(If the installer is currently using a published image, make sure that image already contains the changes from Phases 1-7. Otherwise, build and push the CP Docker image locally first using the project's release script and reference that tag.)

Confirm the CP is up:

```
ssh agent@109.199.123.26 'curl -s http://localhost:8000/healthz'
# expect: {"ok": true}
```

- [ ] **Step 4: Reinstall the daemon on Server 1**

The daemon is co-located with the CP for the smoke. Use the per-CP `install-daemon.sh` endpoint that the CP itself exposes:

```
ssh agent@109.199.123.26 \
  'curl -fsSL http://localhost:8000/install-daemon.sh | sudo bash -s -- --enroll-token <token-from-CP-UI>'
```

To get the enroll token: open the CP UI in a browser at `http://109.199.123.26:8000`, complete the **create admin** form with `admin` / `Password01.2026`, navigate to **Nodes**, click **Add daemon**, copy the enroll token.

Confirm the daemon shows up:

```
sudo systemctl status maestro-daemon
# active (running)
```

The Nodes list in the dashboard should show one connected daemon.

- [ ] **Step 5: Reinstall the daemon on Server 2 pointing at the same CP**

```
ssh agent@38.242.234.47 \
  'sudo systemctl stop maestro-daemon 2>/dev/null; sudo systemctl disable maestro-daemon 2>/dev/null'

ssh agent@38.242.234.47 \
  'curl -fsSL http://109.199.123.26:8000/install-daemon.sh | sudo bash -s -- --enroll-token <token-2-from-CP-UI>'

ssh agent@38.242.234.47 'sudo systemctl status maestro-daemon'
```

The Nodes list in the dashboard should now show two daemons.

- [ ] **Step 6: No commit — this is verification only.**

---

### Task 26: API auth smoke against the real CP

- [ ] **Step 1: Log into the dashboard, create an API key**

In a browser at `http://109.199.123.26:8000`:

1. Log in as `admin` / `Password01.2026`.
2. Go to **Settings → API keys**.
3. Click **Generate API key**, label it `e2e-smoke`.
4. Copy the key (`mae_…`) and the suggested MCP config snippet.

- [ ] **Step 2: Bearer-auth smoke from the dev box**

```
KEY=mae_…   # paste

# 1. Authenticated GET works
curl -fsSL -H "Authorization: Bearer $KEY" \
  http://109.199.123.26:8000/api/state | head

# 2. Anonymous request is rejected
curl -i http://109.199.123.26:8000/api/state | head -5
# expect: HTTP/1.1 401 Unauthorized
# expect body: {"ok":false,"error":{"code":"unauthenticated",...}}

# 3. Invalid Bearer is rejected
curl -i -H "Authorization: Bearer mae_completely_bogus" \
  http://109.199.123.26:8000/api/state | head -5
# expect: 401
```

- [ ] **Step 3: Audit attribution check**

```
ssh agent@109.199.123.26
sudo sqlite3 /var/lib/maestro/cp.db \
  "SELECT applied_by_user_id, kind, applied_at \
   FROM deploy_versions ORDER BY applied_at DESC LIMIT 5;"
```

(Adjust the DB path to match the install — the docker-compose mounts it under `/data/cp.db` inside the container; on the host it's the bind-mount target the installer chose. Verify with `docker inspect`.)

`applied_by_user_id` for any row created during this smoke must be the admin's `usr_…` id, not `singleuser`. Pre-existing rows from earlier sessions will still show `singleuser` and that's fine — they predate the fix.

- [ ] **Step 4: Revoke and re-test**

In the dashboard, revoke `e2e-smoke`. Then:

```
curl -i -H "Authorization: Bearer $KEY" http://109.199.123.26:8000/api/state | head -5
# expect: 401
```

- [ ] **Step 5: Generate a fresh key for the MCP test ahead**

Generate a new key labelled `mcp-deploy-test` and keep it for Task 27. **Do not** revoke this one until Task 27 is complete.

---

### Task 27: MCP-driven deploy of the Maestro website itself

This is the headline smoke: a Claude-Code-style MCP client uses the API key to make Maestro deploy the **Maestro website itself** (the `website/` tree currently served by the existing `caddy:2-alpine` container on Server 1).

- [ ] **Step 1: Verify the website assets and current container layout**

```
ssh agent@109.199.123.26
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Mounts}}' | grep caddy
ls -la ~/website/   # or wherever the bind mount points
```

Record:
- The container name (e.g. `maestro-website`)
- The host path that holds the website files (the bind-mount source)
- The host port (e.g. 80, 8080)

These values feed into the deployment YAML below.

- [ ] **Step 2: Stop and remove the legacy hand-rolled caddy container**

We're going to redeploy it as a proper Maestro component so the smoke tests the deploy pipeline:

```
ssh agent@109.199.123.26 'docker stop <name> && docker rm <name>'
```

- [ ] **Step 3: Author a tiny deployment YAML**

On the dev box, create `/tmp/maestro-website.yaml`:

```yaml
project: maestro-website
hosts:
  cp1:
    host_id: <host-id-of-server-1-from-Nodes-UI>
components:
  website:
    docker:
      image: caddy:2-alpine
      ports:
        - "80:80"
      volumes:
        - "<absolute-host-path-from-step-1>:/usr/share/caddy:ro"
deployment:
  - host: cp1
    components: [website]
```

Replace the bracketed values with the recorded ones from Step 1. The `host_id` is visible in the dashboard's **Nodes** view.

- [ ] **Step 4: Configure a local MCP client**

On the dev box, point Claude Code (or any MCP test harness you prefer) at the Maestro MCP server with the API key from Task 26 Step 5.

Edit `~/.claude/mcp.json` (or the Claude Desktop equivalent — `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "maestro": {
      "command": "python",
      "args": [
        "-m", "app.mcp.server",
        "--control-plane", "http://109.199.123.26:8000"
      ],
      "env": { "MAESTRO_API_KEY": "<key from Task 26 step 5>" },
      "cwd": "<absolute path to control-plane/ in this repo>"
    }
  }
}
```

Restart the MCP client. Confirm `tools/list` returns the Maestro tools (`list_hosts`, `apply_config`, `deploy`, ...).

- [ ] **Step 5: Drive the deployment via MCP**

Inside the MCP client (e.g. ask Claude: *"Use the Maestro tools to apply the YAML at /tmp/maestro-website.yaml and then deploy the website component"*):

1. `apply_config` with the YAML body — expect `{"ok": true, "result": ...}`.
2. `deploy` (or `start website`) — expect the daemon on Server 1 to pull `caddy:2-alpine` and start the container.

If the MCP server is offline / mis-authenticated, the tool result body will read `{"ok": false, "error": {"code": "unauthenticated", ...}}` — fix the env var before continuing.

- [ ] **Step 6: Verify the deploy landed**

```
ssh agent@109.199.123.26 'docker ps | grep caddy'
curl -fsSL http://109.199.123.26/ | head -20
```

The HTTP response must serve the Maestro website's `index.html`.

In the dashboard, the **Deploys** view should show a `maestro-website` deploy with the just-applied version, and `applied_by_user_id` (visible in the version list, or via SQL on the DB) should equal the admin user's id — confirming the MCP-originated apply was correctly attributed.

- [ ] **Step 7: Revoke the MCP key**

Revoke `mcp-deploy-test` from the dashboard. Restart the MCP client and run any tool — the response must be the structured `unauthenticated` error.

- [ ] **Step 8: Final unit-test re-run on the dev box**

After everything works on real infrastructure, do one last:

```
cd control-plane && pytest tests/ -q
cd ../web-ui && npm run build
```

All green.

- [ ] **Step 9: Optional changelog entry**

```
git add CHANGELOG.md   # if maintained
git commit --author="EnzinoBB <genieenzino@gmail.com>" -m "docs: changelog for MCP API-key auth (vX.Y.Z)"
```

---

## Done criteria

- All unit tests pass on the dev box.
- The web-ui build is clean.
- The end-to-end smoke checklist (Tasks 24-27) passes against `109.199.123.26` and `38.242.234.47`.
- The Maestro website serves correctly at `http://109.199.123.26/` after being redeployed via MCP.
- The audit log row for the MCP-driven apply shows the admin user id, not `singleuser`.
- `MAESTRO_SINGLE_USER_MODE` returns no hits in `git grep` other than the design / plan documents.

---

## Done criteria

- All unit tests pass.
- The web-ui build is clean.
- The end-to-end smoke checklist in Task 24 passes.
- `MAESTRO_SINGLE_USER_MODE` returns no hits in `git grep` other than the design / plan documents and a single legacy reference in the test file you may keep around as a deprecation comment (delete it if you can).
- The MCP server, when launched with `MAESTRO_API_KEY`, can apply configs and the audit log shows the correct user id.
