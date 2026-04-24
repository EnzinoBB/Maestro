"""REST router for auth: setup-admin, login, logout, me."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..auth.passwords import hash_password, verify_password
from ..auth.users_repo import UsersRepository, UserAlreadyExists, UserNotFound
from ..auth.middleware import SINGLEUSER_ID, is_single_user_mode


router = APIRouter(prefix="/api/auth")


def _users(request: Request) -> UsersRepository:
    return request.app.state.users_repo


async def _read_json(request: Request) -> dict:
    raw = await request.body()
    if not raw:
        return {}
    import json as _json
    try:
        data = _json.loads(raw.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body")
    return data if isinstance(data, dict) else {}


@router.post("/setup-admin")
async def post_setup_admin(request: Request):
    """Create the first real (non-singleuser) admin.

    Only succeeds while the users table contains just the 'singleuser'
    row. Subsequent calls return 409 — further users are created via
    admin UI (M5.5).
    """
    users = _users(request)
    if await users.count_non_singleuser() > 0:
        raise HTTPException(status_code=409, detail="admin already exists")
    body = await _read_json(request)
    username = body.get("username")
    password = body.get("password")
    if not username or not isinstance(username, str):
        raise HTTPException(status_code=400, detail="'username' is required")
    if not password or not isinstance(password, str) or len(password) < 8:
        raise HTTPException(status_code=400, detail="'password' must be 8+ characters")
    try:
        u = await users.create(
            username=username, password_hash=hash_password(password),
            email=body.get("email"), is_admin=True,
        )
    except UserAlreadyExists as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"id": u["id"], "username": u["username"], "is_admin": u["is_admin"]}


@router.post("/login")
async def post_login(request: Request):
    body = await _read_json(request)
    username = body.get("username")
    password = body.get("password")
    if not username or not password:
        raise HTTPException(status_code=400, detail="'username' and 'password' required")
    users = _users(request)
    u = await users.get_by_username(username)
    if u is None or u["id"] == SINGLEUSER_ID:
        raise HTTPException(status_code=401, detail="invalid credentials")
    if not verify_password(password, u["password_hash"] or ""):
        raise HTTPException(status_code=401, detail="invalid credentials")
    request.session["user_id"] = u["id"]
    return {"id": u["id"], "username": u["username"], "is_admin": u["is_admin"]}


@router.post("/logout")
async def post_logout(request: Request):
    request.session.clear()
    return {"ok": True}


@router.get("/me")
async def get_me(request: Request):
    uid = getattr(request.state, "user_id", None)
    if not uid:
        return {
            "authenticated": False,
            "single_user_mode": is_single_user_mode(),
        }
    users = _users(request)
    try:
        u = await users.get(uid)
    except UserNotFound:
        return {"authenticated": False, "single_user_mode": is_single_user_mode()}
    return {
        "authenticated": True,
        "single_user_mode": is_single_user_mode(),
        "id": u["id"],
        "username": u["username"],
        "is_admin": u["is_admin"],
    }
