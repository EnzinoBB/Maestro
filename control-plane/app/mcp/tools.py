"""Tool implementations shared between MCP server and direct API.

The functions return plain dicts; any adapter (stdio MCP server, HTTP shim)
wraps them. Errors are structured dicts with code + message + suggested_fix.
"""
from __future__ import annotations

import json
from typing import Any

from ..config.loader import parse_deployment, LoaderError
from ..config.validator import validate as semantic_validate
from ..orchestrator import Engine
from ..ws import Hub


def _err(code: str, message: str, *, suggested_fix: str | None = None,
         details: Any = None) -> dict:
    out: dict[str, Any] = {"ok": False, "error": {"code": code, "message": message}}
    if suggested_fix:
        out["error"]["suggested_fix"] = suggested_fix
    if details is not None:
        out["error"]["details"] = details
    return out


class Tools:
    def __init__(self, hub: Hub, engine: Engine, storage):
        self.hub = hub
        self.engine = engine
        self.storage = storage

    async def list_hosts(self) -> dict:
        return {"ok": True, "hosts": self.hub.list_hosts()}

    async def get_state(self) -> dict:
        row = await self.storage.load_config()
        if row is None:
            return {"ok": True, "state": {"components": [], "hosts": self.hub.list_hosts()}}
        try:
            spec = parse_deployment(row[1])
        except LoaderError as e:
            return _err("validation_error", str(e), details=e.errors)
        return {"ok": True, "state": await self.engine.get_state(spec)}

    async def validate_config(self, yaml_text: str) -> dict:
        try:
            spec = parse_deployment(yaml_text)
        except LoaderError as e:
            return _err("validation_error", str(e),
                        details=e.errors,
                        suggested_fix="fix the schema errors listed in details")
        errs = semantic_validate(spec)
        if errs:
            return _err(
                "validation_error", "semantic validation failed",
                details=[e.to_dict() for e in errs],
                suggested_fix="resolve the listed references and cycles",
            )
        return {"ok": True, "project": spec.project,
                "hosts": list(spec.hosts.keys()),
                "components": list(spec.components.keys())}

    async def apply_config(self, yaml_text: str, dry_run: bool = False) -> dict:
        try:
            spec = parse_deployment(yaml_text)
        except LoaderError as e:
            return _err("validation_error", str(e), details=e.errors)
        errs = semantic_validate(spec)
        if errs:
            return _err("validation_error", "semantic validation failed",
                        details=[e.to_dict() for e in errs])
        if not dry_run:
            await self.storage.save_config(spec.project, yaml_text)
        result = await self.engine.apply(spec, dry_run=dry_run)
        if not dry_run:
            await self.storage.record_deploy(spec.project, result.ok, result.to_dict())
        if not result.ok:
            return _err("deploy_failed", result.error or "deploy failed",
                        details=result.to_dict())
        return {"ok": True, "result": result.to_dict()}

    async def deploy(self, project: str | None = None,
                     component_id: str | None = None,
                     host_id: str | None = None) -> dict:
        row = await self.storage.load_config()
        if row is None:
            return _err("not_found", "no configuration applied")
        try:
            spec = parse_deployment(row[1])
        except LoaderError as e:
            return _err("validation_error", str(e), details=e.errors)
        only = None
        if component_id and host_id:
            only = (host_id, component_id)
        elif component_id:
            # resolve host
            for bind in spec.deployment:
                if component_id in bind.components:
                    only = (bind.host, component_id)
                    break
            if only is None:
                return _err("not_found", f"component {component_id} not found")
        result = await self.engine.apply(spec, only=only)
        await self.storage.record_deploy(spec.project, result.ok, result.to_dict())
        if not result.ok:
            return _err("deploy_failed", result.error or "deploy failed",
                        details=result.to_dict())
        return {"ok": True, "result": result.to_dict()}

    async def _op(self, op: str, component_id: str) -> dict:
        row = await self.storage.load_config()
        if row is None:
            return _err("not_found", "no configuration applied")
        try:
            spec = parse_deployment(row[1])
        except LoaderError as e:
            return _err("validation_error", str(e), details=e.errors)
        host = None
        for bind in spec.deployment:
            if component_id in bind.components:
                host = bind.host
                break
        if host is None:
            return _err("not_found", f"component {component_id} not found",
                        suggested_fix="check the current deployment.yaml for valid ids")
        try:
            resp = await self.engine.component_op(host, component_id, op)
        except Exception as e:
            return _err("transport", str(e))
        if not resp.payload.get("ok", True):
            return _err(
                resp.payload.get("error", {}).get("code", "runtime_error"),
                resp.payload.get("error", {}).get("message", f"{op} failed"),
                details=resp.payload.get("error", {}),
            )
        return {"ok": True, "host_id": host, "component_id": component_id, "response": resp.payload}

    async def start(self, component_id: str): return await self._op("start", component_id)
    async def stop(self, component_id: str): return await self._op("stop", component_id)
    async def restart(self, component_id: str): return await self._op("restart", component_id)

    async def tail_logs(self, component_id: str, lines: int = 200) -> dict:
        row = await self.storage.load_config()
        if row is None:
            return _err("not_found", "no configuration applied")
        try:
            spec = parse_deployment(row[1])
        except LoaderError as e:
            return _err("validation_error", str(e), details=e.errors)
        host = None
        for bind in spec.deployment:
            if component_id in bind.components:
                host = bind.host
                break
        if host is None:
            return _err("not_found", f"component {component_id} not found")
        try:
            out = await self.engine.tail_logs(host, component_id, lines=lines)
        except Exception as e:
            return _err("transport", str(e))
        return {"ok": True, "host_id": host, "component_id": component_id,
                "lines": out[-lines:]}
