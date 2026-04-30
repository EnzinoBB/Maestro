"""REST router for nodes + organizations + admin user mgmt (M5.5 / M7 / v0.3)."""
from __future__ import annotations

import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request

from ..auth.deps import require_user
from ..auth.middleware import SINGLEUSER_ID
from ..auth.passwords import hash_password
from ..auth.users_repo import UserAlreadyExists, UserNotFound
from ..storage_nodes import NodeNotFound


router = APIRouter(prefix="/api", dependencies=[Depends(require_user)])


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
async def list_nodes(request: Request, uid: str = Depends(require_user)):
    is_admin = await _resolve_is_admin(request, uid)
    nodes = request.app.state.nodes_repo
    items = await nodes.list_visible_to(uid, is_admin=is_admin)
    # Annotate each node with whether the daemon is currently online.
    hub = request.app.state.hub
    online_set = {h["host_id"] for h in hub.list_hosts() if h["online"]}
    for it in items:
        it["online"] = it["host_id"] in online_set
    return {"nodes": items}


def _read_daemon_token() -> str:
    token = os.environ.get("MAESTRO_DAEMON_TOKEN", "").strip()
    if not token:
        token_file = os.environ.get("MAESTRO_TOKEN_FILE", "/data/daemon-token")
        try:
            with open(token_file, "r", encoding="utf-8") as f:
                token = f.read().strip()
        except OSError:
            token = ""
    return token


def _public_cp_url(request: Request) -> str:
    cp_url = os.environ.get("MAESTRO_PUBLIC_URL", "").rstrip("/")
    if cp_url:
        return cp_url
    host = request.headers.get("host", "")
    scheme = request.url.scheme or "http"
    if host:
        return f"{scheme}://{host}"
    return "http://127.0.0.1:8000"


@router.get("/daemon-enroll")
async def daemon_enroll(request: Request, uid: str = Depends(require_user)):
    """Return cp_url + shared daemon token + a per-caller `claim_user_id`.

    Available to any authenticated user. The shared `MAESTRO_DAEMON_TOKEN`
    gates which daemons may connect at all; the `claim_user_id` is the
    caller's id and is intended to be passed by the install snippet to
    `/ws/daemon?claim=<user_id>` so the resulting node is owned by the
    operator generating the snippet (rather than the first admin).
    """
    token = _read_daemon_token()
    return {
        "cp_url": _public_cp_url(request),
        "token": token,
        "claim_user_id": uid,
        "install_url": "https://github.com/EnzinoBB/Maestro/releases/latest/download/install-daemon.sh",
        "token_available": bool(token),
    }


@router.get("/admin/daemon-enroll")
async def admin_daemon_enroll(request: Request, uid: str = Depends(require_user)):
    """Deprecated alias of /api/daemon-enroll kept for one release."""
    return await daemon_enroll(request, uid)


@router.get("/admin/users")
async def admin_list_users(request: Request, uid: str = Depends(require_user)):
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
    }


@router.post("/admin/users", status_code=201)
async def admin_create_user(request: Request, uid: str = Depends(require_user)):
    """Create a new user (admin only). M7.

    Body: {"username": str, "password": str (8+ chars), "email": str?, "is_admin": bool?}
    """
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
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object")
    username = body.get("username")
    password = body.get("password")
    if not username or not isinstance(username, str):
        raise HTTPException(status_code=400, detail="'username' is required")
    if not password or not isinstance(password, str) or len(password) < 8:
        raise HTTPException(status_code=400, detail="'password' must be 8+ characters")
    if username == SINGLEUSER_ID:
        raise HTTPException(status_code=400, detail=f"'{SINGLEUSER_ID}' is a reserved username")
    users = request.app.state.users_repo
    try:
        u = await users.create(
            username=username,
            password_hash=hash_password(password),
            email=body.get("email"),
            is_admin=bool(body.get("is_admin", False)),
        )
    except UserAlreadyExists as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {
        "id": u["id"], "username": u["username"], "email": u["email"],
        "is_admin": u["is_admin"], "created_at": u["created_at"],
    }


@router.get("/orgs")
async def list_orgs(request: Request, uid: str = Depends(require_user)):
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
async def create_org(request: Request, uid: str = Depends(require_user)):
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


@router.patch("/nodes/{node_id}")
async def admin_update_node(
    request: Request, node_id: str, uid: str = Depends(require_user),
):
    """Pivot a node's type / owner / label. Admin only.

    Body (any subset):
      {"node_type": "user", "owner_user_id": "usr_..."}     # demote shared→user
      {"node_type": "shared", "owner_org_id": "org_..."}    # promote user→shared
      {"label": "rack-7-prod"}                              # rename
      {"label": null}                                       # clear label
    """
    is_admin = await _resolve_is_admin(request, uid)
    if not is_admin:
        raise HTTPException(status_code=403, detail="admin only")
    body: dict = {}
    raw = await request.body()
    if raw:
        import json as _json
        try:
            body = _json.loads(raw.decode("utf-8"))
        except Exception:
            raise HTTPException(status_code=400, detail="invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object")

    node_type = body.get("node_type")
    owner_user_id = body.get("owner_user_id")
    owner_org_id = body.get("owner_org_id")
    label = body.get("label")
    clear_label = "label" in body and label is None

    if node_type is not None and node_type not in ("user", "shared"):
        raise HTTPException(status_code=400, detail="node_type must be 'user' or 'shared'")
    if node_type == "user" and not owner_user_id:
        # Look at the existing row: maybe the caller is only changing label and the
        # node is already user-owned. The repo handles that; reject only if the
        # caller asked for the type change but did not supply the new owner AND
        # the existing row is shared (no owner_user_id to fall back to).
        pass
    nodes = request.app.state.nodes_repo
    try:
        await nodes.get(node_id)
    except NodeNotFound:
        raise HTTPException(status_code=404, detail="node not found")
    # Resolve referenced owners exist
    if owner_user_id:
        try:
            await request.app.state.users_repo.get(owner_user_id)
        except UserNotFound:
            raise HTTPException(status_code=400, detail="owner_user_id does not exist")
    if owner_org_id:
        from ..storage_nodes import OrgNotFound
        try:
            await request.app.state.orgs_repo.get(owner_org_id)
        except OrgNotFound:
            raise HTTPException(status_code=400, detail="owner_org_id does not exist")
    try:
        n = await nodes.update_node(
            node_id,
            node_type=node_type,
            owner_user_id=owner_user_id,
            owner_org_id=owner_org_id,
            label=label if not clear_label else None,
            clear_label=clear_label,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except NodeNotFound:
        raise HTTPException(status_code=404, detail="node not found")
    return n


@router.patch("/admin/users/{user_id}")
async def admin_update_user(
    request: Request, user_id: str, uid: str = Depends(require_user),
):
    """Update mutable fields on a user. Admin only.

    Body: {"is_admin": bool}. Other fields TBD.

    Refuses to demote the last admin (would lock everyone out of admin
    capabilities), and refuses to operate on the singleuser system row.
    """
    is_admin = await _resolve_is_admin(request, uid)
    if not is_admin:
        raise HTTPException(status_code=403, detail="admin only")
    if user_id == SINGLEUSER_ID:
        raise HTTPException(status_code=400, detail="cannot modify the system 'singleuser' row")

    body: dict = {}
    raw = await request.body()
    if raw:
        import json as _json
        try:
            body = _json.loads(raw.decode("utf-8"))
        except Exception:
            raise HTTPException(status_code=400, detail="invalid JSON body")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object")

    users = request.app.state.users_repo
    try:
        u = await users.get(user_id)
    except UserNotFound:
        raise HTTPException(status_code=404, detail="user not found")

    if "is_admin" in body:
        new_admin = bool(body["is_admin"])
        if not new_admin and u["is_admin"]:
            # Block self-demotion if it would leave zero non-singleuser admins
            import aiosqlite
            async with aiosqlite.connect(users.path) as db:
                async with db.execute(
                    "SELECT COUNT(*) FROM users WHERE is_admin=1 "
                    "AND id != ? AND id != 'singleuser'",
                    (user_id,),
                ) as cur:
                    other_admins = (await cur.fetchone())[0]
            if other_admins == 0:
                raise HTTPException(
                    status_code=409,
                    detail="cannot demote the last remaining admin",
                )
        await users.set_admin(user_id, new_admin)
        u = await users.get(user_id)
    return {
        "id": u["id"], "username": u["username"], "email": u["email"],
        "is_admin": u["is_admin"], "created_at": u["created_at"],
    }


@router.delete("/admin/users/{user_id}", status_code=204)
async def admin_delete_user(
    request: Request, user_id: str, uid: str = Depends(require_user),
):
    """Delete a user. Admin only. Refuses 409 if the user owns deploys/nodes.

    api_keys, org_members, node_access cascade away. deploy_versions
    applied_by_user_id is reattributed to 'singleuser' to preserve audit
    history without breaking the FK.
    """
    is_admin = await _resolve_is_admin(request, uid)
    if not is_admin:
        raise HTTPException(status_code=403, detail="admin only")
    if user_id == SINGLEUSER_ID:
        raise HTTPException(status_code=400, detail="cannot delete the system 'singleuser' row")
    if user_id == uid:
        raise HTTPException(status_code=400, detail="cannot delete yourself")

    users = request.app.state.users_repo
    try:
        await users.get(user_id)
    except UserNotFound:
        raise HTTPException(status_code=404, detail="user not found")

    deps = await users.count_dependencies(user_id)
    if deps["deploys"] > 0 or deps["nodes"] > 0:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "user_has_dependencies",
                "message": (
                    f"user owns {deps['deploys']} deploy(s) and {deps['nodes']} "
                    "node(s); reassign or delete those first"
                ),
                "deploys": deps["deploys"],
                "nodes": deps["nodes"],
            },
        )
    await users.delete(user_id)
    from fastapi.responses import Response
    return Response(status_code=204)


@router.post("/admin/users/{user_id}/reset-password")
async def admin_reset_user_password(request: Request, user_id: str, uid: str = Depends(require_user)):
    """Generate a fresh password for the user and return it once.

    Admin-only. The new password is shown to the calling admin who is
    responsible for handing it over via a secure channel — Maestro never
    stores the plaintext. The user's old password is invalidated atomically.

    Refused on the singleuser fixture row (it has no real password).
    """
    is_admin = await _resolve_is_admin(request, uid)
    if not is_admin:
        raise HTTPException(status_code=403, detail="admin only")
    if user_id == SINGLEUSER_ID:
        raise HTTPException(status_code=400, detail="cannot reset password of the system 'singleuser' row")
    users = request.app.state.users_repo
    try:
        u = await users.get(user_id)
    except UserNotFound:
        raise HTTPException(status_code=404, detail="user not found")
    # 12 chars from a 64-char alphabet ≈ 72 bits of entropy. Plenty for a
    # short-lived reset shown once to an admin who will paste it elsewhere.
    new_pw = secrets.token_urlsafe(9)  # ~12 chars after b64
    await users.set_password(u["id"], hash_password(new_pw))
    return {"id": u["id"], "username": u["username"], "new_password": new_pw}
