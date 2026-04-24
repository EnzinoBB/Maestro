"""Current-user resolver: reads the session cookie, populates request.state.user.

In single-user mode (MAESTRO_SINGLE_USER_MODE=true, which is the default
until any real user exists), every request is attributed to the materialized
'singleuser' row without requiring a session.
"""
from __future__ import annotations

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


SINGLEUSER_ID = "singleuser"


def is_single_user_mode() -> bool:
    v = os.environ.get("MAESTRO_SINGLE_USER_MODE")
    if v is None:
        return True  # default ON
    return v.strip().lower() in ("1", "true", "yes", "on")


class CurrentUserMiddleware(BaseHTTPMiddleware):
    """Populates request.state.user_id for every request.

    - If single-user mode → always SINGLEUSER_ID
    - Else: reads session cookie; attaches None if absent/invalid.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        if is_single_user_mode():
            request.state.user_id = SINGLEUSER_ID
        else:
            sess = request.scope.get("session") or {}
            uid = sess.get("user_id") if isinstance(sess, dict) else None
            request.state.user_id = uid if isinstance(uid, str) else None
        return await call_next(request)
