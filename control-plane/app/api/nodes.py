"""REST router for nodes + organizations + admin user listing (M5.5)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..auth.middleware import SINGLEUSER_ID, is_single_user_mode


router = APIRouter(prefix="/api")


def _current_user(request: Request) -> tuple[str, bool]:
    uid = getattr(request.state, "user_id", None)
    if not uid:
        raise HTTPException(status_code=401, detail="authentication required")
    is_admin = bool(getattr(request.state, "is_admin", False))
    # Single-user mode user is always admin.
    if uid == SINGLEUSER_ID:
        is_admin = True
    return uid, is_admin


async def _resolve_is_admin(request: Request, user_id: str) -> bool:
    if user_id == SINGLEUSER_ID:
        return True
    users = request.app.state.users_repo
    try:
        u = await users.get(user_id)
    except Exception:
        return False
    return bool(u.get("is_admin"))


@router.get("/nodes")
async def list_nodes(request: Request):
    uid, _ = _current_user(request)
    is_admin = await _resolve_is_admin(request, uid)
    nodes = request.app.state.nodes_repo
    items = await nodes.list_visible_to(uid, is_admin=is_admin)
    # Annotate each node with whether the daemon is currently online.
    hub = request.app.state.hub
    online_set = {h["host_id"] for h in hub.list_hosts() if h["online"]}
    for it in items:
        it["online"] = it["host_id"] in online_set
    return {"nodes": items}


@router.get("/admin/users")
async def admin_list_users(request: Request):
    uid, _ = _current_user(request)
    is_admin = await _resolve_is_admin(request, uid)
    if not is_admin:
        raise HTTPException(status_code=403, detail="admin only")
    # Read directly to avoid creating a list method on UsersRepository
    # for this single use-case in M5.5; if it grows, promote to repo.
    import aiosqlite
    db_path = request.app.state.users_repo.path
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            "SELECT id, username, email, is_admin, created_at "
            "FROM users ORDER BY created_at ASC"
        ) as cur:
            rows = await cur.fetchall()
    return {
        "users": [
            {
                "id": r[0], "username": r[1], "email": r[2],
                "is_admin": bool(r[3]), "created_at": r[4],
            }
            for r in rows
        ],
        "single_user_mode": is_single_user_mode(),
    }


@router.get("/orgs")
async def list_orgs(request: Request):
    uid, _ = _current_user(request)
    is_admin = await _resolve_is_admin(request, uid)
    orgs = request.app.state.orgs_repo
    items = await orgs.list_all()
    # Non-admins only see orgs they're members of.
    if not is_admin:
        import aiosqlite
        db_path = request.app.state.orgs_repo.path
        async with aiosqlite.connect(db_path) as db:
            async with db.execute(
                "SELECT org_id FROM org_members WHERE user_id=?", (uid,),
            ) as cur:
                allowed = {r[0] for r in await cur.fetchall()}
        items = [o for o in items if o["id"] in allowed]
    return {"orgs": items}


@router.post("/orgs")
async def create_org(request: Request):
    uid, _ = _current_user(request)
    is_admin = await _resolve_is_admin(request, uid)
    if not is_admin:
        raise HTTPException(status_code=403, detail="admin only")
    body = {}
    raw = await request.body()
    if raw:
        import json as _json
        try:
            body = _json.loads(raw.decode("utf-8"))
        except Exception:
            raise HTTPException(status_code=400, detail="invalid JSON body")
    name = body.get("name") if isinstance(body, dict) else None
    if not name or not isinstance(name, str):
        raise HTTPException(status_code=400, detail="'name' is required")
    try:
        o = await request.app.state.orgs_repo.create(name)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return o
