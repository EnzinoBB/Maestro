"""Deployment engine: wire config → hub, respect topological order."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from ..config import DeploymentSpec, render_component
from ..ws import Hub, DaemonOffline, RequestTimeout
from ..ws.protocol import (
    T_REQ_STATE_GET, T_REQ_DEPLOY, T_REQ_START, T_REQ_STOP, T_REQ_RESTART,
    T_REQ_LOGS_TAIL, T_REQ_HEALTH,
)
from .diff import compute_diff, Diff, ComponentChange, component_hash

log = logging.getLogger("rca.engine")


@dataclass
class ComponentDeployResult:
    component_id: str
    host_id: str
    ok: bool
    action: str
    duration_ms: int = 0
    new_hash: str | None = None
    error: dict | None = None

    def to_dict(self) -> dict:
        return {
            "component_id": self.component_id,
            "host_id": self.host_id,
            "ok": self.ok,
            "action": self.action,
            "duration_ms": self.duration_ms,
            "new_hash": self.new_hash,
            "error": self.error,
        }


@dataclass
class DeployResult:
    ok: bool
    results: list[ComponentDeployResult] = field(default_factory=list)
    diff: Diff | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "results": [r.to_dict() for r in self.results],
            "diff": self.diff.to_dict() if self.diff else None,
            "error": self.error,
        }


def _toposort_components(spec: DeploymentSpec) -> list[str]:
    in_deg: dict[str, int] = {cid: 0 for cid in spec.components}
    graph: dict[str, list[str]] = {cid: [] for cid in spec.components}
    for cid, c in spec.components.items():
        for dep in c.depends_on:
            if dep in spec.components:
                graph[dep].append(cid)
                in_deg[cid] += 1
    out: list[str] = []
    ready = [c for c, d in in_deg.items() if d == 0]
    while ready:
        n = ready.pop(0)
        out.append(n)
        for m in graph[n]:
            in_deg[m] -= 1
            if in_deg[m] == 0:
                ready.append(m)
    if len(out) != len(spec.components):
        raise RuntimeError("cycle in component dependencies")
    return out


def _target_bindings(spec: DeploymentSpec) -> list[tuple[str, str]]:
    """Return list of (host_id, component_id) tuples in deploy order."""
    comp_order = _toposort_components(spec)

    # host ordering by depends_on_hosts
    bindings = spec.deployment
    host_in: dict[str, set[str]] = {b.host: set(b.depends_on_hosts) for b in bindings}
    ordered_hosts: list[str] = []
    remaining = list(bindings)
    while remaining:
        progressed = False
        for b in list(remaining):
            if all(h in ordered_hosts for h in b.depends_on_hosts):
                ordered_hosts.append(b.host)
                remaining.remove(b)
                progressed = True
        if not progressed:
            # cycle; just flatten the rest
            for b in remaining:
                ordered_hosts.append(b.host)
            remaining = []

    tuples: list[tuple[str, str]] = []
    for host in ordered_hosts:
        bind = next(b for b in bindings if b.host == host)
        host_comps = set(bind.components)
        for cid in comp_order:
            if cid in host_comps:
                tuples.append((host, cid))
    return tuples


class Engine:
    def __init__(self, hub: Hub) -> None:
        self.hub = hub

    # ---- state retrieval ------------------------------------------------

    async def get_observed_state(
        self, spec: DeploymentSpec, *, timeout: float = 5.0,
    ) -> dict[tuple[str, str], dict[str, Any]]:
        """Return {(host_id, component_id): state_dict}. Offline hosts → empty."""
        out: dict[tuple[str, str], dict[str, Any]] = {}
        for host_id in {b.host for b in spec.deployment}:
            if not self.hub.is_online(host_id):
                continue
            try:
                resp = await self.hub.request(host_id, T_REQ_STATE_GET, {}, timeout=timeout)
            except (DaemonOffline, RequestTimeout) as e:
                log.warning("state.get failed for %s: %s", host_id, e)
                continue
            for comp in resp.payload.get("components", []):
                out[(host_id, comp["id"])] = comp
        return out

    # ---- diff -----------------------------------------------------------

    def render_all(
        self, spec: DeploymentSpec, *, template_store: dict[str, str] | None = None,
    ) -> dict[tuple[str, str], dict[str, Any]]:
        desired: dict[tuple[str, str], dict[str, Any]] = {}
        for bind in spec.deployment:
            for cid in bind.components:
                rc = render_component(spec, cid, bind.host, template_store=template_store)
                desired[(bind.host, cid)] = rc.to_payload()
        return desired

    async def diff(
        self, spec: DeploymentSpec, *, template_store: dict[str, str] | None = None,
    ) -> Diff:
        desired = self.render_all(spec, template_store=template_store)
        observed = await self.get_observed_state(spec)
        observed_hashes = {
            k: v.get("component_hash") for k, v in observed.items()
        }
        return compute_diff(desired, observed_hashes)

    # ---- deploy ---------------------------------------------------------

    async def apply(
        self,
        spec: DeploymentSpec,
        *,
        template_store: dict[str, str] | None = None,
        dry_run: bool = False,
        timeout_per_component: float = 600.0,
        only: tuple[str, str] | None = None,  # (host, component) filter
    ) -> DeployResult:
        try:
            desired = self.render_all(spec, template_store=template_store)
        except Exception as e:
            return DeployResult(ok=False, error=f"render failed: {e}")

        observed = await self.get_observed_state(spec)
        observed_hashes = {k: v.get("component_hash") for k, v in observed.items()}
        diff = compute_diff(desired, observed_hashes)

        if dry_run:
            return DeployResult(ok=True, diff=diff)

        results: list[ComponentDeployResult] = []
        order = _target_bindings(spec)

        for host_id, cid in order:
            if only is not None and (host_id, cid) != only:
                continue
            change = next(
                (c for c in diff.changes
                 if c.host_id == host_id and c.component_id == cid),
                None,
            )
            if change is None:
                continue
            if change.action == "unchanged":
                results.append(ComponentDeployResult(
                    component_id=cid, host_id=host_id,
                    ok=True, action="unchanged", new_hash=change.new_hash,
                ))
                continue
            if change.action == "remove":
                # Fase 1: we don't remove automatically unless --prune. Skip.
                results.append(ComponentDeployResult(
                    component_id=cid, host_id=host_id,
                    ok=True, action="skip_remove",
                ))
                continue

            payload = dict(desired[(host_id, cid)])
            payload["target_hash"] = change.new_hash
            payload["deploy_mode"] = "cold"
            payload["timeout_sec"] = int(timeout_per_component)

            t0 = asyncio.get_running_loop().time()
            try:
                resp = await self.hub.request(
                    host_id, T_REQ_DEPLOY, payload, timeout=timeout_per_component,
                )
            except (DaemonOffline, RequestTimeout) as e:
                results.append(ComponentDeployResult(
                    component_id=cid, host_id=host_id, ok=False,
                    action=change.action,
                    error={"code": "transport", "message": str(e)},
                ))
                return DeployResult(ok=False, results=results, diff=diff,
                                    error=f"{host_id}/{cid}: {e}")
            dur = int((asyncio.get_running_loop().time() - t0) * 1000)

            ok = bool(resp.payload.get("ok", False))
            if ok:
                results.append(ComponentDeployResult(
                    component_id=cid, host_id=host_id,
                    ok=True, action=change.action,
                    duration_ms=dur,
                    new_hash=resp.payload.get("new_hash") or change.new_hash,
                ))
            else:
                results.append(ComponentDeployResult(
                    component_id=cid, host_id=host_id,
                    ok=False, action=change.action,
                    duration_ms=dur,
                    error=resp.payload.get("error"),
                ))
                return DeployResult(ok=False, results=results, diff=diff,
                                    error=f"{host_id}/{cid} failed")
        return DeployResult(ok=True, results=results, diff=diff)

    # ---- single-component ops ------------------------------------------

    async def component_op(
        self, host_id: str, component_id: str, op: str,
        *, timeout: float = 60.0, extra_payload: dict | None = None,
    ):
        req_map = {
            "start": T_REQ_START, "stop": T_REQ_STOP, "restart": T_REQ_RESTART,
            "healthcheck": T_REQ_HEALTH,
        }
        if op not in req_map:
            raise ValueError(f"unknown op {op}")
        payload = {"component_id": component_id}
        if extra_payload:
            payload.update(extra_payload)
        return await self.hub.request(host_id, req_map[op], payload, timeout=timeout)

    async def tail_logs(self, host_id: str, component_id: str, lines: int = 200,
                        *, timeout: float = 20.0) -> list[str]:
        resp = await self.hub.request(
            host_id, T_REQ_LOGS_TAIL,
            {"component_id": component_id, "lines": lines},
            timeout=timeout,
        )
        return list(resp.payload.get("lines", []))

    async def get_state(self, spec: DeploymentSpec) -> dict:
        observed = await self.get_observed_state(spec)
        out: list[dict] = []
        for (hid, cid), state in observed.items():
            out.append({
                "host_id": hid,
                "component_id": cid,
                **state,
            })
        # include known components on hosts that are offline as unknown
        for bind in spec.deployment:
            for cid in bind.components:
                if (bind.host, cid) not in observed:
                    out.append({
                        "host_id": bind.host,
                        "component_id": cid,
                        "id": cid,
                        "status": "unknown" if self.hub.is_online(bind.host) else "host_offline",
                    })
        return {
            "project": spec.project,
            "components": out,
            "hosts": self.hub.list_hosts(),
        }
