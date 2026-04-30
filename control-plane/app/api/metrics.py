"""REST router for time-series metrics + events."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from ..auth.deps import require_user


router = APIRouter(prefix="/api", dependencies=[Depends(require_user)])


_VALID_SCOPES = {"host", "component", "deploy"}


@router.get("/metrics/{scope}/{scope_id}")
async def get_metric_range(
    request: Request,
    scope: str,
    scope_id: str,
    metric: str = Query(..., min_length=1),
    from_ts: float = Query(...),
    to_ts: float = Query(...),
):
    if scope not in _VALID_SCOPES:
        raise HTTPException(status_code=400, detail=f"invalid scope: {scope}")
    repo = request.app.state.metrics_repo
    rows = await repo.range(
        scope=scope, scope_id=scope_id, metric=metric,
        from_ts=from_ts, to_ts=to_ts,
    )
    return {
        "scope": scope, "scope_id": scope_id, "metric": metric,
        "points": [[t, v] for (t, v) in rows],
    }


@router.get("/events")
async def list_events(
    request: Request,
    scope: str | None = None,
    scope_id: str | None = None,
    kind: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
):
    if scope is not None and scope not in _VALID_SCOPES:
        raise HTTPException(status_code=400, detail=f"invalid scope: {scope}")
    repo = request.app.state.metrics_repo
    events = await repo.list_events(scope=scope, scope_id=scope_id, kind=kind, limit=limit)
    return {"events": events}
