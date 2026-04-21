"""Render a single component: resolve templates, vars, run spec."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
import base64

import jinja2

from .schema import DeploymentSpec, ComponentSpec


@dataclass
class RenderedConfigFile:
    dest: str
    mode: int
    content: str

    @property
    def content_b64(self) -> str:
        return base64.b64encode(self.content.encode("utf-8")).decode("ascii")


@dataclass
class RenderedComponent:
    component_id: str
    host_id: str
    source: dict[str, Any]
    build_steps: list[dict[str, Any]] = field(default_factory=list)
    config_files: list[RenderedConfigFile] = field(default_factory=list)
    run: dict[str, Any] = field(default_factory=dict)
    healthcheck: dict[str, Any] | None = None
    secrets: dict[str, str] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "source": self.source,
            "build_steps": self.build_steps,
            "config_files": [
                {"dest": f.dest, "mode": f.mode, "content_b64": f.content_b64}
                for f in self.config_files
            ],
            "run": self.run,
            "healthcheck": self.healthcheck,
            "secrets": self.secrets,
        }


class RenderError(Exception):
    pass


def _env() -> jinja2.Environment:
    env = jinja2.Environment(
        undefined=jinja2.StrictUndefined,
        keep_trailing_newline=True,
        autoescape=False,
    )
    return env


_VAULT_RE = re.compile(r"{{\s*vault://[^}]+}}")


def _render_str(s: str, ctx: dict[str, Any]) -> str:
    # ignore vault:// references in Fase 1: leave empty string; they are
    # expected to be resolved by the credential backend. The daemon won't
    # receive them unless present in `secrets`.
    if _VAULT_RE.search(s):
        return _VAULT_RE.sub("", s)
    try:
        return _env().from_string(s).render(**ctx)
    except jinja2.UndefinedError as e:
        raise RenderError(f"undefined variable: {e.message}") from e
    except jinja2.TemplateError as e:
        raise RenderError(str(e)) from e


def _walk(obj: Any, ctx: dict[str, Any]) -> Any:
    if isinstance(obj, str):
        return _render_str(obj, ctx)
    if isinstance(obj, list):
        return [_walk(x, ctx) for x in obj]
    if isinstance(obj, dict):
        return {k: _walk(v, ctx) for k, v in obj.items()}
    return obj


def _ctx(spec: DeploymentSpec, component: ComponentSpec, component_id: str, host_id: str) -> dict[str, Any]:
    hosts_ctx = {hid: h.model_dump() for hid, h in spec.hosts.items()}
    # `hosts['id'].address` form is supported out of the box because dict
    # lookups work in Jinja2 with the subscript syntax.
    rendered_vars: dict[str, Any] = {}
    for k, v in component.config.vars.items():
        if isinstance(v, str):
            rendered_vars[k] = _render_str(v, {"hosts": hosts_ctx})
        else:
            rendered_vars[k] = v
    return {
        "hosts": hosts_ctx,
        "components": {cid: c.model_dump() for cid, c in spec.components.items()},
        "component": component.model_dump(),
        "component_id": component_id,
        "host_id": host_id,
        "config": {"vars": rendered_vars},
        "source": component.source.model_dump(),
        "vars": rendered_vars,
    }


def _read_template_content(template_source: str, raw_templates: dict[str, str] | None) -> str:
    """Look up a template by name in an optional in-memory map.
    In Fase 1 we do not load files from disk — only inline content is supported
    to keep the server-side render stateless. If not found, the source string
    itself is used as template content (useful for tests)."""
    if raw_templates and template_source in raw_templates:
        return raw_templates[template_source]
    # last resort: treat the source as a literal template string
    return template_source


def render_component(
    spec: DeploymentSpec,
    component_id: str,
    host_id: str,
    *,
    template_store: dict[str, str] | None = None,
) -> RenderedComponent:
    if component_id not in spec.components:
        raise RenderError(f"component '{component_id}' not found")
    if host_id not in spec.hosts:
        raise RenderError(f"host '{host_id}' not found")

    component = spec.components[component_id]
    ctx = _ctx(spec, component, component_id, host_id)

    # Render run as a dict of walked values, so `{{ source.image }}` etc. resolve
    run_dict = _walk(component.run.model_dump(), ctx)

    # Infer run.image when docker source and run has no explicit image
    if run_dict.get("type") == "docker" and not run_dict.get("image"):
        if component.source.type == "docker" and component.source.image:
            tag = component.source.tag or "latest"
            run_dict["image"] = f"{component.source.image}:{tag}"

    # healthcheck
    hc_dict: dict[str, Any] | None = None
    if component.healthcheck is not None:
        hc_dict = _walk(component.healthcheck.model_dump(), ctx)

    # source
    source_dict = _walk(component.source.model_dump(), ctx)

    # build steps
    build_steps = []
    for step in component.build:
        build_steps.append({
            "command": _render_str(step.command, ctx),
            "env": {k: _render_str(v, ctx) for k, v in step.env.items()},
            "working_dir": step.working_dir,
            "timeout": step.timeout,
        })

    # config files (templates)
    config_files: list[RenderedConfigFile] = []
    for t in component.config.templates:
        tmpl_content = _read_template_content(t.source, template_store)
        rendered = _render_str(tmpl_content, ctx)
        config_files.append(RenderedConfigFile(
            dest=_render_str(t.dest, ctx),
            mode=t.mode,
            content=rendered,
        ))

    return RenderedComponent(
        component_id=component_id,
        host_id=host_id,
        source=source_dict,
        build_steps=build_steps,
        config_files=config_files,
        run=run_dict,
        healthcheck=hc_dict,
        secrets={},  # fase 1: no vault
    )
