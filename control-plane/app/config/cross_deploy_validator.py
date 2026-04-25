"""Cross-deploy conflict checks run at apply-time over other deploys' current versions."""
from __future__ import annotations

from dataclasses import dataclass

from .schema import DeploymentSpec


@dataclass(frozen=True)
class CrossDeployConflict:
    kind: str  # 'component_id_collision' | 'host_port_collision'
    host: str
    component_id: str | None = None
    host_port: int | None = None
    other_deploy_id: str | None = None
    other_component_id: str | None = None
    message: str = ""


def _placements(spec: DeploymentSpec) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for bind in spec.deployment:
        for cid in bind.components:
            out.append((bind.host, cid))
    return out


def _host_ports_for_component(spec: DeploymentSpec, component_id: str) -> list[int]:
    comp = spec.components.get(component_id)
    if comp is None:
        return []
    run = comp.run
    ports: list[int] = []
    raw_ports = getattr(run, "ports", None) or []
    for p in raw_ports:
        s = str(p)
        host_side = s.split(":")[0] if ":" in s else s
        try:
            ports.append(int(host_side))
        except (TypeError, ValueError):
            continue
    return ports


def check_cross_deploy_conflicts(
    mine: DeploymentSpec,
    others: dict[str, DeploymentSpec],
) -> list[CrossDeployConflict]:
    """Return conflicts between `mine` and each spec in `others` (keyed by deploy_id).

    The caller is responsible for excluding the current deploy's id from `others`.
    """
    out: list[CrossDeployConflict] = []
    my_placements = set(_placements(mine))
    my_port_claims: dict[tuple[str, int], str] = {}
    for host, cid in my_placements:
        for p in _host_ports_for_component(mine, cid):
            my_port_claims[(host, p)] = cid

    for other_id, other in others.items():
        other_placements = _placements(other)
        for host, cid in other_placements:
            if (host, cid) in my_placements:
                out.append(CrossDeployConflict(
                    kind="component_id_collision",
                    host=host, component_id=cid,
                    other_deploy_id=other_id, other_component_id=cid,
                    message=(f"component '{cid}' on host '{host}' is already "
                             f"bound by deploy '{other_id}'"),
                ))
        for host, cid in other_placements:
            for p in _host_ports_for_component(other, cid):
                if (host, p) in my_port_claims:
                    out.append(CrossDeployConflict(
                        kind="host_port_collision",
                        host=host, host_port=p,
                        component_id=my_port_claims[(host, p)],
                        other_deploy_id=other_id, other_component_id=cid,
                        message=(f"host port {p} on '{host}' claimed by component "
                                 f"'{cid}' in deploy '{other_id}'"),
                    ))
    return out
