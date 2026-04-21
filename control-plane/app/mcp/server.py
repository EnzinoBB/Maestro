"""Standalone MCP server over stdio, sharing state with the control plane.

Usage:
    python -m app.mcp.server --control-plane http://localhost:8000

The MCP server in Fase 1 delegates to the HTTP API of the running control
plane (so state stays centralized). It does NOT embed the control plane
process; start the control plane first.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import httpx

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
    MCP_AVAILABLE = True
except Exception:  # pragma: no cover
    MCP_AVAILABLE = False


def _schema_yaml_only() -> dict:
    return {"type": "object", "properties": {"yaml_text": {"type": "string"}},
            "required": ["yaml_text"]}


def _schema_component() -> dict:
    return {"type": "object", "properties": {"component_id": {"type": "string"}},
            "required": ["component_id"]}


def _schema_logs() -> dict:
    return {"type": "object", "properties": {
        "component_id": {"type": "string"},
        "lines": {"type": "integer", "default": 200},
    }, "required": ["component_id"]}


class MCPClient:
    def __init__(self, base: str):
        self.base = base.rstrip("/")

    async def _post(self, path: str, json_body=None, params=None) -> dict:
        async with httpx.AsyncClient(timeout=300.0) as c:
            r = await c.post(self.base + path, json=json_body, params=params or {})
            try:
                return r.json()
            except Exception:
                return {"ok": False, "error": {"code": "http", "message": r.text}}

    async def _post_yaml(self, path: str, yaml_text: str, params=None) -> dict:
        async with httpx.AsyncClient(timeout=300.0) as c:
            r = await c.post(self.base + path, content=yaml_text,
                             headers={"content-type": "text/yaml"},
                             params=params or {})
            try:
                return r.json()
            except Exception:
                return {"ok": False, "error": {"code": "http", "message": r.text}}

    async def _get(self, path: str, params=None) -> dict:
        async with httpx.AsyncClient(timeout=60.0) as c:
            r = await c.get(self.base + path, params=params or {})
            try:
                return r.json()
            except Exception:
                return {"ok": False, "error": {"code": "http", "message": r.text}}


async def run(base_url: str):
    if not MCP_AVAILABLE:
        print("mcp SDK not available; install 'mcp' package", file=sys.stderr)
        sys.exit(1)

    client = MCPClient(base_url)
    server = Server("rca")

    tools_def = [
        Tool(name="list_hosts", description="List daemons currently connected to the control plane.",
             inputSchema={"type": "object", "properties": {}}),
        Tool(name="get_state", description="Return aggregated state of the current project.",
             inputSchema={"type": "object", "properties": {}}),
        Tool(name="validate_config", description="Validate YAML config (schema + semantics).",
             inputSchema=_schema_yaml_only()),
        Tool(name="apply_config", description="Apply YAML config; set dry_run=true for no-op preview.",
             inputSchema={"type": "object", "properties": {
                 "yaml_text": {"type": "string"},
                 "dry_run": {"type": "boolean", "default": False},
             }, "required": ["yaml_text"]}),
        Tool(name="deploy", description="Deploy the current config (optionally a single component).",
             inputSchema={"type": "object", "properties": {
                 "component_id": {"type": "string"},
                 "host_id": {"type": "string"},
             }}),
        Tool(name="start", description="Start a component.",
             inputSchema=_schema_component()),
        Tool(name="stop", description="Stop a component.",
             inputSchema=_schema_component()),
        Tool(name="restart", description="Restart a component.",
             inputSchema=_schema_component()),
        Tool(name="tail_logs", description="Return last N log lines for a component.",
             inputSchema=_schema_logs()),
    ]

    @server.list_tools()
    async def list_tools():
        return tools_def

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        try:
            if name == "list_hosts":
                data = await client._get("/api/hosts")
            elif name == "get_state":
                data = await client._get("/api/state")
            elif name == "validate_config":
                data = await client._post_yaml("/api/config/validate", arguments["yaml_text"])
            elif name == "apply_config":
                dry = bool(arguments.get("dry_run", False))
                data = await client._post_yaml(
                    "/api/config/apply", arguments["yaml_text"],
                    params={"dry_run": str(dry).lower()},
                )
            elif name == "deploy":
                body = {k: v for k, v in arguments.items() if v}
                data = await client._post("/api/deploy", json_body=body)
            elif name in ("start", "stop", "restart"):
                cid = arguments["component_id"]
                data = await client._post(f"/api/components/{cid}/{name}")
            elif name == "tail_logs":
                cid = arguments["component_id"]
                lines = int(arguments.get("lines", 200))
                data = await client._get(f"/api/components/{cid}/logs",
                                         params={"lines": lines})
            else:
                data = {"ok": False, "error": {"code": "not_found",
                                               "message": f"unknown tool {name}"}}
        except Exception as e:
            data = {"ok": False, "error": {"code": "internal", "message": str(e)}}
        return [TextContent(type="text", text=json.dumps(data, default=str))]

    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--control-plane", default="http://localhost:8000",
                    help="Base URL of a running control plane.")
    args = ap.parse_args()
    asyncio.run(run(args.control_plane))


if __name__ == "__main__":
    main()
