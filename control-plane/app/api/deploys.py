"""REST router for multi-deploy CRUD + versions + apply + rollback."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from ..config.cross_deploy_validator import check_cross_deploy_conflicts
from ..config.hashing import components_hash_from_rendered
from ..config.loader import parse_deployment, LoaderError
from ..config.validator import validate as semantic_validate
from ..orchestrator import Engine
from ..storage_deploys import DeployRepository, DeployNotFound, DeployVersionNotFound


router = APIRouter(prefix="/api/deploys")


def _repo(request: Request) -> DeployRepository:
    return request.app.state.deploy_repo


def _current_user_id(request: Request) -> str:
    """M1 stub: always resolve to the materialized singleuser row.
    M5 will replace this with middleware that reads the session cookie.
    """
    return "singleuser"


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
            raise HTTPException(
                status_code=400,
                detail="template_store and files_store must be objects",
            )
        for name, store in (("template_store", ts), ("files_store", fs)):
            for k, v in store.items():
                if not isinstance(v, str):
                    raise HTTPException(
                        status_code=400,
                        detail=(f"{name} values must be strings, got "
                                f"{type(v).__name__} for key '{k}'"),
                    )
        return str(data["yaml_text"]), dict(ts), dict(fs)
    return raw.decode("utf-8", errors="replace"), {}, {}


# ---------- CRUD ----------

@router.get("")
async def list_deploys(request: Request):
    user = _current_user_id(request)
    return {"deploys": await _repo(request).list_for_owner(user)}


@router.post("", status_code=201)
async def create_deploy(request: Request):
    user = _current_user_id(request)
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
        raise HTTPException(status_code=400, detail="'name' is required and must be a string")
    try:
        d = await _repo(request).create(name, owner_user_id=user)
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
    return {**d, "versions": await repo.list_versions(deploy_id)}


@router.delete("/{deploy_id}", status_code=204)
async def delete_deploy(request: Request, deploy_id: str):
    try:
        await _repo(request).delete(deploy_id)
    except DeployNotFound:
        raise HTTPException(status_code=404, detail="deploy not found")
    return Response(status_code=204)


# ---------- validate / diff / apply ----------

@router.post("/{deploy_id}/validate")
async def validate_on_deploy(request: Request, deploy_id: str):
    try:
        await _repo(request).get(deploy_id)
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
    try:
        await _repo(request).get(deploy_id)
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

    # Cross-deploy conflict check
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
