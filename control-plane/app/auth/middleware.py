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
