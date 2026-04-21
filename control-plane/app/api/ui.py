"""HTMX helper endpoints returning small HTML fragments."""
from __future__ import annotations

import html
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, PlainTextResponse

from ..config.loader import parse_deployment, LoaderError
from ..config.validator import validate as semantic_validate
from ..orchestrator import Engine


router = APIRouter(prefix="/ui")


def _esc(x) -> str:
    return html.escape(str(x), quote=True) if x is not None else ""


def _badge(status: str) -> str:
    cls = f"b-{_esc(status).replace(' ', '_')}"
    return f'<span class="badge {cls}">{_esc(status)}</span>'


@router.get("/hosts", response_class=HTMLResponse)
async def ui_hosts(request: Request):
    hosts = request.app.state.hub.list_hosts()
    if not hosts:
        return HTMLResponse("<em>No daemons connected.</em>")
    rows = "".join(
        f"<tr><td>{_esc(h['host_id'])}</td>"
        f"<td>{_badge('online' if h['online'] else 'offline')}</td>"
        f"<td>{_esc(h.get('daemon_version') or '-')}</td>"
        f"<td>{_esc(','.join(h.get('runners', [])))}</td></tr>"
        for h in hosts
    )
    return HTMLResponse(
        f"<table><thead><tr><th>Host</th><th>Status</th><th>Version</th><th>Runners</th></tr></thead><tbody>{rows}</tbody></table>"
    )


@router.get("/state-table", response_class=HTMLResponse)
async def ui_state_table(request: Request):
    storage = request.app.state.storage
    engine: Engine = request.app.state.engine
    row = await storage.load_config()
    if row is None:
        return HTMLResponse("<em>No configuration applied.</em>")
    try:
        spec = parse_deployment(row[1])
    except LoaderError as e:
        return HTMLResponse(f"<div class='msg msg-err'>Stored YAML invalid: {_esc(e)}</div>")
    state = await engine.get_state(spec)
    items = state.get("components", [])
    if not items:
        return HTMLResponse("<em>No components known.</em>")
    rows = []
    for c in items:
        status = c.get("status") or "unknown"
        row_html = (
            "<tr>"
            f"<td>{_esc(c.get('component_id'))}</td>"
            f"<td>{_esc(c.get('host_id'))}</td>"
            f"<td>{_badge(status)}</td>"
            f"<td>{_esc(c.get('runner') or '-')}</td>"
            f"<td>{_esc((c.get('component_hash') or '-')[:12])}</td>"
            f"<td>"
            f"<button class='secondary' hx-post='/api/components/{_esc(c.get('component_id'))}/start' hx-swap='none'>Start</button> "
            f"<button class='secondary' hx-post='/api/components/{_esc(c.get('component_id'))}/stop' hx-swap='none'>Stop</button> "
            f"<button class='secondary' hx-post='/api/components/{_esc(c.get('component_id'))}/restart' hx-swap='none'>Restart</button>"
            f"</td>"
            "</tr>"
        )
        rows.append(row_html)
    return HTMLResponse(
        "<table><thead><tr><th>Component</th><th>Host</th><th>Status</th><th>Runner</th><th>Hash</th><th>Actions</th></tr></thead><tbody>"
        + "".join(rows) + "</tbody></table>"
    )


@router.get("/load-current", response_class=PlainTextResponse)
async def ui_load_current(request: Request):
    storage = request.app.state.storage
    row = await storage.load_config()
    if row is None:
        return PlainTextResponse("")
    return PlainTextResponse(row[1])


def _render_errors(errs: list[dict]) -> str:
    if not errs:
        return ""
    items = "".join(
        f"<li><code>{_esc(e.get('path', ''))}</code>: {_esc(e.get('message', ''))}</li>"
        for e in errs
    )
    return f"<ul>{items}</ul>"


@router.post("/validate", response_class=HTMLResponse)
async def ui_validate(request: Request):
    form = await request.form()
    yaml_text = str(form.get("yaml_text", ""))
    try:
        spec = parse_deployment(yaml_text)
    except LoaderError as e:
        return HTMLResponse(
            f"<div class='msg msg-err'>Schema error: {_esc(e)}{_render_errors(e.errors)}</div>"
        )
    errs = semantic_validate(spec)
    if errs:
        return HTMLResponse(
            "<div class='msg msg-err'>Validation errors:"
            + _render_errors([e.to_dict() for e in errs])
            + "</div>"
        )
    return HTMLResponse(
        f"<div class='msg msg-ok'>OK — project <b>{_esc(spec.project)}</b>, "
        f"{len(spec.hosts)} host(s), {len(spec.components)} component(s).</div>"
    )


@router.post("/diff", response_class=HTMLResponse)
async def ui_diff(request: Request):
    form = await request.form()
    yaml_text = str(form.get("yaml_text", ""))
    try:
        spec = parse_deployment(yaml_text)
    except LoaderError as e:
        return HTMLResponse(f"<div class='msg msg-err'>{_esc(e)}</div>")
    errs = semantic_validate(spec)
    if errs:
        return HTMLResponse(
            "<div class='msg msg-err'>Validation errors:"
            + _render_errors([e.to_dict() for e in errs])
            + "</div>"
        )
    engine: Engine = request.app.state.engine
    d = await engine.diff(spec)
    def _render(label, items):
        if not items: return ""
        body = "".join(
            f"<li><code>{_esc(c.host_id)}/{_esc(c.component_id)}</code>"
            f" {_esc((c.old_hash or '-')[:10])} → {_esc((c.new_hash or '-')[:10])}</li>"
            for c in items
        )
        return f"<h4>{label}</h4><ul>{body}</ul>"
    body = (
        _render("Create", d.to_create)
        + _render("Update", d.to_update)
        + _render("Remove", d.to_remove)
        + _render("Unchanged", d.unchanged)
    )
    return HTMLResponse(f"<div class='msg msg-ok'>Diff computed:</div>{body}")


@router.post("/apply", response_class=HTMLResponse)
async def ui_apply(request: Request, dry_run: bool = Query(False)):
    form = await request.form()
    yaml_text = str(form.get("yaml_text", ""))
    try:
        spec = parse_deployment(yaml_text)
    except LoaderError as e:
        return HTMLResponse(f"<div class='msg msg-err'>{_esc(e)}</div>")
    errs = semantic_validate(spec)
    if errs:
        return HTMLResponse(
            "<div class='msg msg-err'>Validation errors:"
            + _render_errors([e.to_dict() for e in errs])
            + "</div>"
        )
    engine: Engine = request.app.state.engine
    storage = request.app.state.storage
    if not dry_run:
        await storage.save_config(spec.project, yaml_text)
    result = await engine.apply(spec, dry_run=dry_run)
    if not dry_run:
        await storage.record_deploy(spec.project, result.ok, result.to_dict())
    if result.ok:
        rows = "".join(
            f"<li><code>{_esc(r.host_id)}/{_esc(r.component_id)}</code>: "
            f"{_esc(r.action)} ({r.duration_ms}ms)</li>"
            for r in result.results
        )
        return HTMLResponse(f"<div class='msg msg-ok'>Deploy OK</div><ul>{rows}</ul>")
    err = _esc(result.error or "deploy failed")
    return HTMLResponse(f"<div class='msg msg-err'>{err}</div>")


@router.get("/history", response_class=HTMLResponse)
async def ui_history(request: Request):
    storage = request.app.state.storage
    items = await storage.history(limit=10)
    if not items:
        return HTMLResponse("<em>no history</em>")
    rows = "".join(
        f"<tr><td>{_esc(i['id'])}</td>"
        f"<td>{_esc(i['project'])}</td>"
        f"<td>{_badge('ok' if i['ok'] else 'failed')}</td>"
        f"<td>{_esc(i['ts'])}</td></tr>"
        for i in items
    )
    return HTMLResponse(
        f"<table><thead><tr><th>ID</th><th>Project</th><th>Result</th><th>TS</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )
