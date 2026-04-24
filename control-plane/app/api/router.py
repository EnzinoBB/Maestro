"""REST endpoints that drive the control plane."""
from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse

from ..config.loader import parse_deployment, LoaderError
from ..config.validator import validate as semantic_validate
from ..orchestrator import Engine


router = APIRouter(prefix="/api")


def _errors_payload(code: str, message: str, errors: list[dict] | None = None) -> dict:
    return {"ok": False, "error": {"code": code, "message": message, "errors": errors or []}}


async def _read_apply_body(request: Request) -> tuple[str, dict[str, str], dict[str, str]]:
    """Return (yaml_text, template_store, files_store).

    Accepts JSON {yaml_text: ..., template_store?: {name:content}, files_store?: {source:tar_b64}}
    or raw yaml/text body (with empty stores)."""
    ct = (request.headers.get("content-type") or "").split(";")[0].strip()
    raw = await request.body()
    if ct == "application/json":
        import json as _json
        try:
            data = _json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            raise HTTPException(status_code=400, detail="invalid JSON body")
        if not isinstance(data, dict) or "yaml_text" not in data:
            raise HTTPException(status_code=400, detail="JSON body must include 'yaml_text'")
        ts = data.get("template_store") or {}
        fs = data.get("files_store") or {}
        if not isinstance(ts, dict) or not isinstance(fs, dict):
            raise HTTPException(status_code=400, detail="template_store and files_store must be objects")
        for name, store in (("template_store", ts), ("files_store", fs)):
            for k, v in store.items():
                if not isinstance(v, str):
                    raise HTTPException(
                        status_code=400,
                        detail=f"{name} values must be strings, got {type(v).__name__} for key '{k}'",
                    )
        return str(data["yaml_text"]), dict(ts), dict(fs)
    return raw.decode("utf-8", errors="replace"), {}, {}


async def _read_yaml_body(request: Request) -> str:
    """Accept JSON {yaml_text: ...} or raw yaml/text body.
    Kept as alias for backward compatibility with /api/config/validate and /api/config/diff."""
    y, _, _ = await _read_apply_body(request)
    return y


@router.get("/healthz")
async def healthz():
    return {"ok": True}


@router.get("/hosts")
async def list_hosts(request: Request):
    hub = request.app.state.hub
    return {"hosts": hub.list_hosts()}


@router.get("/config")
async def get_config(request: Request):
    storage = request.app.state.storage
    row = await storage.load_config()
    if row is None:
        return {"project": None, "yaml_text": None, "applied_at": None}
    return {"project": row[0], "yaml_text": row[1], "applied_at": row[2]}


@router.post("/config/validate")
async def post_validate(request: Request):
    yaml_text = await _read_yaml_body(request)
    try:
        spec = parse_deployment(yaml_text)
    except LoaderError as e:
        return JSONResponse(
            _errors_payload("validation_error", str(e), e.errors),
            status_code=400,
        )
    errs = semantic_validate(spec)
    if errs:
        return JSONResponse(
            {"ok": False, "errors": [e.to_dict() for e in errs]},
            status_code=400,
        )
    return {
        "ok": True,
        "project": spec.project,
        "hosts": list(spec.hosts.keys()),
        "components": list(spec.components.keys()),
    }


@router.post("/config/diff")
async def post_diff(request: Request):
    yaml_text = await _read_yaml_body(request)
    try:
        spec = parse_deployment(yaml_text)
    except LoaderError as e:
        raise HTTPException(status_code=400, detail=str(e))
    errs = semantic_validate(spec)
    if errs:
        raise HTTPException(status_code=400, detail=[e.to_dict() for e in errs])
    engine: Engine = request.app.state.engine
    d = await engine.diff(spec)
    return {"ok": True, "diff": d.to_dict()}


@router.post("/config/apply")
async def post_apply(request: Request):
    yaml_text, template_store, files_store = await _read_apply_body(request)
    dry_run = request.query_params.get("dry_run", "false").lower() == "true"
    try:
        spec = parse_deployment(yaml_text)
    except LoaderError as e:
        raise HTTPException(status_code=400, detail=str(e))
    errs = semantic_validate(spec)
    if errs:
        raise HTTPException(status_code=400, detail=[e.to_dict() for e in errs])
    engine: Engine = request.app.state.engine
    storage = request.app.state.storage
    if not dry_run:
        await storage.save_config(spec.project, yaml_text)
    result = await engine.apply(spec, dry_run=dry_run,
                                template_store=template_store, files_store=files_store)
    if not dry_run:
        await storage.record_deploy(spec.project, result.ok, result.to_dict())
    return result.to_dict()


@router.post("/deploy")
async def post_deploy(request: Request, body: dict[str, Any] | None = Body(None)):
    body = body or {}
    storage = request.app.state.storage
    engine: Engine = request.app.state.engine
    row = await storage.load_config()
    if row is None:
        raise HTTPException(status_code=404, detail="no config applied yet")
    _, yaml_text, _ = row
    try:
        spec = parse_deployment(yaml_text)
    except LoaderError as e:
        raise HTTPException(status_code=400, detail=str(e))
    only = None
    if body.get("host_id") and body.get("component_id"):
        only = (body["host_id"], body["component_id"])
    result = await engine.apply(spec, only=only)
    await storage.record_deploy(spec.project, result.ok, result.to_dict())
    return result.to_dict()


@router.get("/state")
async def get_state(request: Request):
    storage = request.app.state.storage
    engine: Engine = request.app.state.engine
    row = await storage.load_config()
    if row is None:
        return {"project": None, "components": [], "hosts": engine.hub.list_hosts()}
    _, yaml_text, _ = row
    try:
        spec = parse_deployment(yaml_text)
    except LoaderError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await engine.get_state(spec)


async def _resolve_host_for_component(request: Request, component_id: str) -> str:
    storage = request.app.state.storage
    row = await storage.load_config()
    if row is None:
        raise HTTPException(status_code=404, detail="no config applied")
    _, yaml_text, _ = row
    spec = parse_deployment(yaml_text)
    for bind in spec.deployment:
        if component_id in bind.components:
            return bind.host
    raise HTTPException(status_code=404, detail=f"component {component_id} not found")


@router.post("/components/{cid}/{op}")
async def component_op(request: Request, cid: str, op: str):
    if op not in ("start", "stop", "restart", "healthcheck"):
        raise HTTPException(status_code=400, detail=f"unknown op: {op}")
    engine: Engine = request.app.state.engine
    host = await _resolve_host_for_component(request, cid)
    try:
        resp = await engine.component_op(host, cid, op)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"ok": True, "response": resp.payload}


@router.get("/components/{cid}/logs")
async def component_logs(request: Request, cid: str, lines: int = 200):
    engine: Engine = request.app.state.engine
    host = await _resolve_host_for_component(request, cid)
    try:
        lines_out = await engine.tail_logs(host, cid, lines=lines)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"ok": True, "host_id": host, "component_id": cid, "lines": lines_out}


@router.get("/deploys")
async def deploys(request: Request, limit: int = 20):
    storage = request.app.state.storage
    return {"history": await storage.history(limit=limit)}
