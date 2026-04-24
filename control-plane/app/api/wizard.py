"""REST router for wizard support endpoints."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ..wizard.docker_inspect import inspect_image


router = APIRouter(prefix="/api/wizard")


@router.post("/docker/inspect")
async def post_docker_inspect(request: Request):
    body = {}
    raw = await request.body()
    if raw:
        import json as _json
        try:
            body = _json.loads(raw.decode("utf-8"))
        except Exception:
            raise HTTPException(status_code=400, detail="invalid JSON body")
    image = body.get("image") if isinstance(body, dict) else None
    if not image or not isinstance(image, str):
        raise HTTPException(status_code=400, detail="'image' is required")
    tag = body.get("tag") or "latest"
    sug = await inspect_image(image, tag)
    return {
        "exposed_ports": sug.exposed_ports,
        "env": sug.env,
        "volumes": sug.volumes,
    }
