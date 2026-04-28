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
