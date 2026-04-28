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
            detail=f"'label' must be <={LABEL_MAX_CHARS} characters",
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
        "key": full_key,
        "warning": "Save this key now. You will not be able to see it again.",
    }


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
