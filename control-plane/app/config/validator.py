"""Semantic validation: referential integrity, cycles, dry-run template check."""
from __future__ import annotations

from dataclasses import dataclass
from .schema import DeploymentSpec


@dataclass
class ValidationError:
    path: str
    message: str
    code: str = "validation_error"

    def to_dict(self) -> dict:
        return {"path": self.path, "message": self.message, "code": self.code}


def _detect_cycle(graph: dict[str, list[str]]) -> list[str] | None:
    WHITE, GRAY, BLACK = 0, 1, 2
    colors = {n: WHITE for n in graph}
    parent: dict[str, str | None] = {n: None for n in graph}

    def dfs(u: str) -> list[str] | None:
        colors[u] = GRAY
        for v in graph.get(u, []):
            if v not in colors:
                continue
            if colors[v] == GRAY:
                cycle = [v, u]
                p = parent[u]
                while p is not None and p != v:
                    cycle.append(p)
                    p = parent[p]
                cycle.append(v)
                return list(reversed(cycle))
            if colors[v] == WHITE:
                parent[v] = u
                c = dfs(v)
                if c:
                    return c
        colors[u] = BLACK
        return None

    for n in list(graph.keys()):
        if colors[n] == WHITE:
            c = dfs(n)
            if c:
                return c
    return None


def validate(spec: DeploymentSpec) -> list[ValidationError]:
    errors: list[ValidationError] = []

    # 1. components referenced in deployment.* must exist
    for i, bind in enumerate(spec.deployment):
        if bind.host not in spec.hosts:
            errors.append(ValidationError(
                path=f"deployment[{i}].host",
                message=f"host '{bind.host}' not defined in hosts",
            ))
        for j, c in enumerate(bind.components):
            if c not in spec.components:
                errors.append(ValidationError(
                    path=f"deployment[{i}].components[{j}]",
                    message=f"component '{c}' not defined in components",
                ))
        for j, h in enumerate(bind.depends_on_hosts):
            if h not in spec.hosts:
                errors.append(ValidationError(
                    path=f"deployment[{i}].depends_on_hosts[{j}]",
                    message=f"host '{h}' not defined in hosts",
                ))

    # 2. depends_on between components must resolve
    graph = {cid: [] for cid in spec.components}
    for cid, c in spec.components.items():
        for dep in c.depends_on:
            if dep not in spec.components:
                errors.append(ValidationError(
                    path=f"components.{cid}.depends_on",
                    message=f"component '{dep}' not defined",
                ))
            else:
                graph[cid].append(dep)

    # 3. cycle detection
    cycle = _detect_cycle(graph)
    if cycle:
        errors.append(ValidationError(
            path="components",
            message=f"dependency cycle: {' -> '.join(cycle)}",
        ))

    # 4. run.type coherence: if source is docker image, run.type must be docker
    for cid, c in spec.components.items():
        if c.source.type == "docker" and c.run.type != "docker":
            errors.append(ValidationError(
                path=f"components.{cid}.run.type",
                message="source.type=docker requires run.type=docker",
            ))

    # 5. deploy_mode != cold is accepted but only cold is functional in Fase 1
    # (warn as error to keep behaviour predictable)
    for cid, c in spec.components.items():
        if c.deploy_mode != "cold":
            errors.append(ValidationError(
                path=f"components.{cid}.deploy_mode",
                message=f"deploy_mode='{c.deploy_mode}' not supported in Phase 1 (only 'cold')",
                code="unsupported_feature",
            ))

    # 6. kubernetes hosts not supported in Fase 1
    for hid, h in spec.hosts.items():
        if h.type == "kubernetes":
            errors.append(ValidationError(
                path=f"hosts.{hid}.type",
                message="kubernetes hosts not supported in Phase 1",
                code="unsupported_feature",
            ))

    return errors
