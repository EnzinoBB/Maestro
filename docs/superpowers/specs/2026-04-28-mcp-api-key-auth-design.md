# MCP API-Key Auth & Universal `/api/*` Hardening — Design

**Date:** 2026-04-28
**Status:** Approved (brainstorming phase complete, pending implementation plan)
**Scope:** Introduce per-user API keys generated from the user dashboard, used by the MCP stdio server (and any other automation client) to authenticate to the Control Plane. As part of the same change, close an existing security gap by requiring authentication on **all** `/api/*` endpoints (cookie session for the web UI, Bearer API key for everything else). Deprecate `MAESTRO_SINGLE_USER_MODE`.

---

## 1. Context & goals

Today's state of authentication on the Control Plane:

- The web UI uses a session cookie issued by `/api/auth/login`.
- The MCP stdio server (`app/mcp/server.py`) proxies HTTP calls to the CP **without any authentication**.
- The legacy `/api/*` endpoints (`/api/config/apply`, `/api/state`, `/api/components/{id}/start`, etc.) **do not check authentication at all** in multi-user mode. Anyone who reaches port 8000 can apply configs and operate components without logging in.
- Every operation through these legacy endpoints is recorded in the audit log as `applied_by_user_id="singleuser"` regardless of who triggered it, because the router hardcodes the value (see [`app/api/router.py:79, 162-173`](../../control-plane/app/api/router.py)).
- `MAESTRO_SINGLE_USER_MODE` exists as an env-var flag that bypasses authentication entirely, attributing every request to the seeded `singleuser` row.

**Goals of this design:**

1. Per-user **API keys** generated from the user dashboard. Multiple keys per user, each with a user-supplied label, individually revocable.
2. **One auth mechanism for all `/api/*` endpoints**: cookie session (web UI) **or** `Authorization: Bearer mae_…` (MCP and other automations). No endpoint reachable anonymously except a strictly-defined public set.
3. **Correct audit attribution**: operations on the legacy `default` deploy are recorded with the real caller's `user_id`, not the hardcoded `singleuser`.
4. **Deprecate `MAESTRO_SINGLE_USER_MODE`** entirely. Auth is always required. The flag is removed from the codebase, the installer, the docs, and the UI.

**Non-goals:** see §10.

---

## 2. Architecture overview

A single new auth surface:

- A new SQLite table `api_keys` stores hashed keys with a per-user label.
- A rewritten `CurrentUserMiddleware` accepts **either** a session cookie (existing behaviour) **or** an `Authorization: Bearer mae_…` header. It populates `request.state.user_id` and updates `last_used_at` on the key row.
- A FastAPI dependency `require_user` is attached at the `APIRouter` level to every router under `/api/*`, except a small explicit allowlist of public endpoints (login, setup-admin, me, healthz, static UI assets).
- A new REST router `/api/auth/keys` for self-service key management (list, create, revoke).
- A new screen `/settings` in the web UI with an **API keys** section. The "Change password" affordance is moved here from the user-menu popover.
- The MCP stdio server reads `MAESTRO_API_KEY` from the environment at start and injects it as a Bearer header on every HTTP call to the CP.
- The legacy router is patched to read `request.state.user_id` for `applied_by_user_id`, instead of hardcoding `singleuser`.
- `MAESTRO_SINGLE_USER_MODE` is removed from middleware, installer, docs, and the web UI.

The `singleuser` row remains in the `users` table as a system placeholder owning legacy data (the `default` deploy and any unattributed legacy `deploy_versions` rows). It cannot authenticate, has no password, and cannot own API keys.

---

## 3. Database schema

A new table is added to `_SCHEMA` in [`app/storage.py`](../../control-plane/app/storage.py):

```sql
CREATE TABLE IF NOT EXISTS api_keys (
    id           TEXT PRIMARY KEY,                  -- 'ak_' + 8 hex
    user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    label        TEXT NOT NULL,                     -- free-form, max 64 chars
    prefix       TEXT NOT NULL,                     -- first 9 chars of the key, e.g. 'mae_abc12'
    key_hash     TEXT NOT NULL,                     -- argon2/bcrypt hash of the full key
    created_at   REAL NOT NULL,
    last_used_at REAL,                              -- updated on each authenticated request
    revoked_at   REAL                               -- soft-revoke; NULL = active
);
CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_prefix ON api_keys(prefix);
```

**Key format:** `mae_` + `secrets.token_urlsafe(32)` → ~52 chars total.
Example: `mae_abc12defghijklmn0pqrs1tuv2wxy3zABC4DEF5GH`.
The `prefix` column stores the first 9 characters (`mae_abc12`) for fast lookup; this is the only piece of the key visible after creation.

**Hashing:** the same `hash_password` / `verify_password` helpers in [`app/auth/passwords.py`](../../control-plane/app/auth/passwords.py) used for user passwords. We do not need a separate algorithm.

**Revocation:** soft. A revoked key sets `revoked_at` to `time.time()` but is not deleted. The auth middleware filters `WHERE revoked_at IS NULL`. A future "purge revoked" UI can hard-delete; for now revoked rows remain visible in the dashboard so users can audit retired credentials.

**Last-used:** updated on each successful authentication, best-effort. The update runs in a detached `asyncio.create_task` from the middleware so it does not block the request, and any error is logged but swallowed (we do not want a stale `last_used_at` to fail an otherwise-valid request). A few seconds of staleness is acceptable.

**No standalone migration script.** Since there are no existing deployments yet, the table is added to the canonical `_SCHEMA` and created on first boot via `Storage.init_schema()`'s existing idempotent `CREATE TABLE IF NOT EXISTS` pattern.

---

## 4. Authentication middleware

`CurrentUserMiddleware` in [`app/auth/middleware.py`](../../control-plane/app/auth/middleware.py) is rewritten. Pseudocode:

```python
class CurrentUserMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        user_id = await self._authenticate(request)
        request.state.user_id = user_id
        return await call_next(request)

    async def _authenticate(self, request) -> str | None:
        # 1. Bearer API key takes precedence
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            key = auth[7:].strip()
            uid = await self._verify_api_key(key)
            if uid:
                return uid
            # invalid key: fall through to None — do NOT fall back to cookie

        # 2. Session cookie
        sess = request.scope.get("session") or {}
        uid = sess.get("user_id") if isinstance(sess, dict) else None
        return uid if isinstance(uid, str) else None

    async def _verify_api_key(self, key: str) -> str | None:
        if not key.startswith("mae_") or len(key) < 12:
            return None
        prefix = key[:9]
        rows = await self.api_keys_repo.list_active_by_prefix(prefix)
        for row in rows:
            if verify_password(key, row["key_hash"]):
                # fire-and-forget last_used_at update
                asyncio.create_task(self.api_keys_repo.touch_last_used(row["id"]))
                return row["user_id"]
        return None
```

**Why prefix lookup:** avoids hashing the presented key against every row in `api_keys`. The 8-byte (~40-bit) entropy of the prefix makes collisions effectively non-existent in realistic key counts; in case of collision we iterate.

**Cost:** one argon2 verification per request that presents a Bearer key (~100ms). Acceptable for the API request rates expected. Cookie-authenticated requests pay zero hashing cost.

**Invalid Bearer does not fall back to cookie.** A request that presents *any* `Authorization: Bearer …` header is treated as a key-auth attempt. If the key is invalid, the request is unauthenticated, period. This avoids a class of confused-deputy issues where a stolen-but-revoked key could be silently ignored while the session cookie keeps things working.

### Authorization gate

Authentication-required routers declare a router-level dependency:

```python
from fastapi import APIRouter, Depends
from app.auth.deps import require_user

router = APIRouter(dependencies=[Depends(require_user)])
```

`require_user` raises `HTTPException(401, …)` if `request.state.user_id` is `None`, and `403` if it equals `"singleuser"` (defence-in-depth: with the new model nothing can authenticate as `singleuser` anyway — no password, no key — but we make the rejection explicit at the gate). The 401/403 responses are formatted as `{"ok": false, "error": {"code": "unauthenticated" | "forbidden", "message": "..."}}` via a custom FastAPI `exception_handler` that overrides the default `HTTPException` body shape.

**Public endpoints** (NOT wrapped by `require_user`):

- `POST /api/auth/login`
- `POST /api/auth/setup-admin` (gated by "no real admin yet" check inside the handler)
- `GET  /api/auth/me`
- `GET  /healthz` (if/when added)
- Static UI assets

All other `/api/*` paths require authentication.

### `MAESTRO_SINGLE_USER_MODE` deprecation

The flag is removed entirely:

- `app/auth/middleware.py`: `is_single_user_mode()` and the `SINGLEUSER_ID` middleware branch are deleted.
- `app/api/auth.py`: `GET /api/auth/me` no longer reports `single_user_mode`. The `needs_setup` flag is computed purely from `users.count_non_singleuser() == 0`.
- `scripts/install-cp.sh`: `MAESTRO_SINGLE_USER_MODE` is removed from the generated `docker-compose.yml`. The `--single-user` CLI flag is removed.
- `web-ui/src/components/UserMenuPopover.tsx`: the `state.status === "single-user"` branch is removed.
- `web-ui/src/hooks/useAuth.ts`: the `"single-user"` status is removed from the union type.
- `README.md`: sections describing the flag (lines 58-65) are rewritten to describe the new auth model.

---

## 5. REST API for key management

A new router `app/api/api_keys.py` mounted under `/api/auth/keys`. All endpoints require `require_user` and reject `singleuser` as caller.

### `GET /api/auth/keys` — list own keys

Response body:

```json
{
  "keys": [
    {
      "id": "ak_8f3a2c1b",
      "label": "claude-code-laptop",
      "prefix": "mae_abc12",
      "created_at": 1714248000.0,
      "last_used_at": 1714291200.0,
      "revoked_at": null
    },
    {
      "id": "ak_92ef10d4",
      "label": "ci-pipeline",
      "prefix": "mae_xyz98",
      "created_at": 1714200000.0,
      "last_used_at": null,
      "revoked_at": 1714220000.0
    }
  ]
}
```

Always filtered to `WHERE user_id = caller`. Includes both active and revoked keys; the UI distinguishes them via `revoked_at`.

### `POST /api/auth/keys` — generate a new key

Request body: `{"label": "claude-code-laptop"}`.

Validation:

- `label`: non-empty string, ≤64 chars, must be unique among the caller's **active** keys (a label freed by revocation can be reused).

Behaviour:

1. Generate the token: `secrets.token_urlsafe(32)` → prepend `mae_` → full key.
2. Compute `prefix = key[:9]`, `key_hash = hash_password(key)`.
3. `INSERT INTO api_keys` with `revoked_at = NULL`.
4. Return the cleartext key **once**:

```json
{
  "id": "ak_8f3a2c1b",
  "label": "claude-code-laptop",
  "prefix": "mae_abc12",
  "key": "mae_abc12defghijklmn...",
  "created_at": 1714248000.0,
  "warning": "Save this key now. You will not be able to see it again."
}
```

**Limit:** max **10 active keys per user** (revoked keys do not count). Exceeding the limit returns `409 Conflict` with `{"ok": false, "error": {"code": "max_keys_reached", "message": "..."}}`. The cap is arbitrary but bounds bot/runaway-script damage.

### `DELETE /api/auth/keys/{key_id}` — revoke

Soft-revoke: `UPDATE api_keys SET revoked_at = ? WHERE id = ? AND user_id = caller`. Idempotent: revoking an already-revoked key still returns 204.

The middleware filters revoked keys, so a revoked key stops working at the **next** request. There is no in-flight cancellation.

### Rejected cases

- Caller is `singleuser` → `403`.
- Caller is anonymous → `401` (handled by `require_user`).
- `key_id` belongs to another user → `404` (not `403`, to avoid leaking the existence of other users' keys).

### Audit

Both `POST` and `DELETE` write a row into the existing `metric_events` table ([`app/storage.py:73-82`](../../control-plane/app/storage.py)) with:

- `kind = "api_key.created"` or `"api_key.revoked"`
- `scope = "user"`, `scope_id = user_id`
- `payload_json = {"key_id": "...", "label": "..."}`

No new audit-log table is introduced.

---

## 6. Web UI

### New screen: `/settings`

A new file `web-ui/src/screens/settings.tsx` provides a per-user settings page. It is the new home for:

- **Account** — username, email, "Change password" (moved from `UserMenuPopover`).
- **API keys** — new section described below.

Routing: a new route `/settings` is added to the React Router setup. The `UserMenuPopover` gains a `Settings` menu item that navigates to `/settings`; it loses the direct "Change password" button (the dialog component is reused inside the new screen).

### "API keys" section

**Empty state:** title, short explainer, and a primary "Generate API key" button.

> *API keys allow external tools (like the Claude Code MCP server) to access Maestro on your behalf. Anyone with a key has the same permissions as you do — keep them secret.*

**Populated state:** a table with columns:

- **Label** (`claude-code-laptop`)
- **Prefix** (mono, `mae_abc12…`)
- **Created** (relative time, e.g. "3 days ago")
- **Last used** (relative time, or "Never")
- **Status** (pill: green `active` / grey `revoked`)
- **Actions** (`Revoke` for active keys; nothing for revoked)

A primary "Generate new key" button sits above the table.

### Generate flow (modal, two steps)

**Step 1 — label input:** focused text field (1-64 chars, live duplicate check), Cancel/Generate buttons.

**Step 2 — one-time display:** after a successful `POST /api/auth/keys`:

- Bold warning banner: *"Save this key now. You won't be able to see it again."*
- Read-only `<input>` containing the full key, with a Copy button (`navigator.clipboard.writeText`).
- A copy-pasteable MCP config snippet:

```json
{
  "mcpServers": {
    "maestro": {
      "command": "python",
      "args": ["-m", "app.mcp.server", "--control-plane", "<CP-URL>"],
      "env": { "MAESTRO_API_KEY": "mae_abc12...xyz" }
    }
  }
}
```

- Buttons: **Copy config** (primary) and **I've saved it, close** (secondary, only way to dismiss the modal — ESC and backdrop-click are disabled to force acknowledgement).

If the POST returns `409 max_keys_reached`, the modal shows an inline error with a "manage keys" link back to the table.

### Revoke flow

Confirm dialog:

> *Revoke key '{label}'? Tools using this key will stop working immediately. This cannot be undone.*

Primary destructive button **Revoke** (red), secondary **Cancel**. On confirmation: `DELETE` → on 204 the row updates to `status: revoked`, actions disappear.

### `UserMenuPopover` cleanup

The popover items become:

```
[avatar block]
─────────────
Settings              → /settings
─────────────
Switch user
Sign out
```

The `state.status === "single-user"` branch and all references to `MAESTRO_SINGLE_USER_MODE` are removed.

---

## 7. MCP stdio server

Changes to [`app/mcp/server.py`](../../control-plane/app/mcp/server.py):

```python
import os

def _auth_headers() -> dict:
    key = os.environ.get("MAESTRO_API_KEY")
    return {"Authorization": f"Bearer {key}"} if key else {}

class MCPClient:
    async def _post(self, path, json_body=None, params=None):
        async with httpx.AsyncClient(timeout=300.0) as c:
            r = await c.post(self.base + path, json=json_body,
                             params=params or {}, headers=_auth_headers())
            ...
    # _post_yaml and _get changed identically
```

No CLI flag, no config file. `MAESTRO_API_KEY` is the single mechanism.

**Behaviour when the key is missing or invalid:**

- Missing env var → no `Authorization` header → CP responds 401 → `tools.py` returns `{"ok": false, "error": {"code": "unauthenticated", "message": "Set MAESTRO_API_KEY in your MCP server config"}}`. The error surfaces as a tool result in the MCP client; the user sees a clear message.
- Invalid or revoked key → same flow, same error. No client-side pre-check.

The `--control-plane` CLI flag is unchanged.

### Documentation

`README.md` gets a new section "Using the MCP server" with the exact `claude_desktop_config.json` snippet that the dashboard generates. The dashboard's snippet and the README must remain in sync — implementation note for the plan.

---

## 8. Legacy router: correct audit attribution

In [`app/api/router.py`](../../control-plane/app/api/router.py):

- `applied_by_user_id="singleuser"` (line 173) → `applied_by_user_id=request.state.user_id`.
- `get_by_name("singleuser", "default")` (lines 79, 162): unchanged. The legacy `default` deploy continues to be owned by `singleuser` as a placeholder. Per-user multi-deploy is the M2-M5 milestone work and is out of scope here.
- `create("default", owner_user_id="singleuser")` (line 164): unchanged, same reason.

Net effect: the version history of the `default` deploy now reflects the actual user who applied each version (cookie or key). The deploy itself is still owned by the system row.

In [`app/storage_migrate.py`](../../control-plane/app/storage_migrate.py): the one-shot legacy YAML migration continues to use `singleuser` as `applied_by_user_id` (no real user to attribute it to).

---

## 9. Testing strategy

### Unit tests

- `tests/unit/test_api_keys_repo.py`: CRUD, prefix lookup, revoke, last-used update, max-keys-per-user.
- `tests/unit/test_middleware_api_key.py`: valid Bearer → user_id; invalid Bearer → None (no cookie fallback); valid cookie → user_id; both present → Bearer wins; revoked key → None; `singleuser`-owned key → rejected at creation.
- `tests/unit/test_api_auth_keys.py`: `GET`/`POST`/`DELETE` for the new router; ownership checks; 401/403/404/409 paths; audit-event emission.
- `tests/unit/test_legacy_router_attribution.py`: `applied_by_user_id` reflects the cookie user, then the Bearer-key user, never `singleuser`.

### Integration tests

- `tests/integration/test_mcp_auth.py`: spawn the MCP server with a valid `MAESTRO_API_KEY` against a live CP; call `apply_config`; assert `deploy_versions.applied_by_user_id` matches the key's owner.
- Same with missing/invalid key; assert tool result contains the unauthenticated error.

### Manual verification

- Wire a real Claude Code instance to the MCP server with a generated key. Apply a config. Confirm attribution by reading `deploy_versions` directly (`SELECT applied_by_user_id, applied_at, kind FROM deploy_versions ORDER BY applied_at DESC LIMIT 5;`) — there is no dedicated audit/history view in the dashboard yet (M2-M5 work).
- Generate, list, revoke a key from the UI; confirm the modal flow matches the spec.
- Confirm an unauthenticated request to a protected endpoint (e.g. `curl http://cp:8000/api/state`) returns 401 with the structured error body.

---

## 10. Non-goals (explicit YAGNI)

- **Per-key scopes / permissions.** All keys grant the full powers of the owning user. Scoped keys (read-only, deploy-specific) can come later if a use case emerges.
- **Automatic rotation / expiry.** Keys live until revoked.
- **IP allowlists per key.**
- **Per-key rate limiting.** A future hardening concern.
- **API keys for `singleuser`.** Explicitly rejected; the row is a system placeholder.
- **Migration of existing deployments.** None exist; the schema additive change is enough.
- **OAuth, OIDC, SSO.** Out of scope; this design covers local-account auth only.
- **Auth on the daemon WebSocket channel.** That uses its own enrollment-token mechanism and is unaffected.

---

## 11. Open questions

None. All key design decisions were made during brainstorming:

| Decision | Choice |
|---|---|
| Scope of auth change | All `/api/*` (B) |
| Key granularity | N keys per user, with label (B) |
| Visibility after creation | One-time display, hash in DB (A) |
| Settings toggle for MCP | None — presence of keys is the toggle (A) |
| Transport from MCP client | Env var → `Authorization: Bearer` header (A) |
| Single-user-mode interaction | Deprecated; auth always required (A) |
