"""E2e MCP integration: reproduces the tool calls an agent would make.

Because Fase 1 MCP server forwards to the HTTP API, we exercise the same
code paths by instantiating `app.mcp.tools.Tools` against a live control
plane, making this script self-contained and scriptable by the agent
developer.

Running:
    CP_URL=http://127.0.0.1:8000 python tests/e2e/test_mcp_integration.py

The script exits 0 on success, non-zero otherwise. It prints a line per step.
"""
from __future__ import annotations

import os
import sys
import time
import json
import urllib.request
import urllib.error


CP = os.environ.get("CP_URL", "http://127.0.0.1:8000")


def http(method: str, path: str, body: bytes | None = None,
         headers: dict | None = None) -> tuple[int, dict | str]:
    req = urllib.request.Request(CP + path, method=method, data=body,
                                 headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
            try:
                return r.status, json.loads(raw)
            except Exception:
                return r.status, raw.decode()
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw.decode()


def step(name: str, fn):
    print(f"[step] {name}...", flush=True)
    try:
        fn()
        print(f"  ✓ {name}", flush=True)
    except AssertionError as e:
        print(f"  ✗ {name}: {e}", flush=True)
        sys.exit(1)


YAML = """api_version: rca/v1
project: mcp-e2e
hosts:
  host1: {type: linux, address: 127.0.0.1, user: deploy}
components:
  probe:
    source: {type: docker, image: nginx, tag: 1.27-alpine}
    run:
      type: docker
      container_name: rca-mcp-probe
      ports: ["18099:80"]
      restart: unless-stopped
    healthcheck:
      type: http
      url: http://127.0.0.1:18099/
      expect_status: 200
      interval: 2s
      start_period: 3s
      retries: 5
    deploy_mode: cold
deployment:
  - host: host1
    components: [probe]
"""


def main():
    # 1. list_hosts
    def check_hosts():
        _, d = http("GET", "/api/hosts")
        assert isinstance(d, dict) and "hosts" in d, d
        assert len(d["hosts"]) >= 1, d
    step("list_hosts", check_hosts)

    # 2. validate_config
    def validate():
        code, d = http("POST", "/api/config/validate",
                       body=YAML.encode(),
                       headers={"content-type": "text/yaml"})
        assert code == 200, (code, d)
        assert d["ok"] is True, d
    step("validate_config", validate)

    # 3. apply_config
    def apply():
        code, d = http("POST", "/api/config/apply",
                       body=YAML.encode(),
                       headers={"content-type": "text/yaml"})
        assert code == 200, (code, d)
        assert d["ok"] is True, d
        # ensure the probe was touched
        ids = {r["component_id"] for r in d["results"]}
        assert "probe" in ids, d
    step("apply_config", apply)

    # 4. get_state -> probe running
    def check_state():
        for _ in range(20):
            _, d = http("GET", "/api/state")
            comps = d.get("components", [])
            running = [c for c in comps if c.get("component_id") == "probe" and c.get("status") == "running"]
            if running:
                return
            time.sleep(1)
        raise AssertionError(f"probe not running, state={d}")
    step("get_state=running", check_state)

    # 5. tail_logs
    def logs():
        _, d = http("GET", "/api/components/probe/logs?lines=5")
        assert d["ok"] is True, d
        assert isinstance(d["lines"], list), d
    step("tail_logs", logs)

    # 6. stop / start / restart
    for op in ("stop", "start", "restart"):
        def _op(op=op):
            _, d = http("POST", f"/api/components/probe/{op}")
            assert d["ok"] is True, d
        step(f"component_op:{op}", _op)
        time.sleep(1)

    # 7. idempotency: re-apply yields unchanged
    def idem():
        _, d = http("POST", "/api/config/apply",
                    body=YAML.encode(),
                    headers={"content-type": "text/yaml"})
        assert d["ok"] is True, d
        assert all(r["action"] in ("unchanged", "skip_remove") for r in d["results"]), d
    step("idempotency", idem)

    print("[ok] MCP-equivalent round-trip passed.")


if __name__ == "__main__":
    main()
