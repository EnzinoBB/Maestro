"""Pure helpers for parsing docker image inspect output, plus a best-effort
shell-out that performs the actual inspection on a host with docker available."""
from __future__ import annotations

import asyncio
import json
import subprocess
from dataclasses import dataclass, field


@dataclass
class DockerSuggestions:
    exposed_ports: list[int] = field(default_factory=list)
    env: list[dict[str, str]] = field(default_factory=list)
    volumes: list[str] = field(default_factory=list)


def parse_docker_inspect(raw: str) -> DockerSuggestions:
    """Parse the JSON output of `docker image inspect <ref>`.

    Returns empty suggestions on malformed input so the caller can display
    the wizard without suggestions rather than crashing.
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return DockerSuggestions()
    if not isinstance(data, list) or not data:
        return DockerSuggestions()
    first = data[0]
    if not isinstance(first, dict):
        return DockerSuggestions()
    cfg = first.get("Config") or {}
    if not isinstance(cfg, dict):
        return DockerSuggestions()

    ports: list[int] = []
    for key in (cfg.get("ExposedPorts") or {}):
        s = str(key)
        if not s.endswith("/tcp"):
            continue
        num = s.split("/", 1)[0]
        try:
            ports.append(int(num))
        except ValueError:
            continue

    env_list: list[dict[str, str]] = []
    for line in cfg.get("Env") or []:
        s = str(line)
        if "=" not in s:
            continue
        k, v = s.split("=", 1)
        env_list.append({"key": k, "value": v})

    volumes: list[str] = []
    for vol in (cfg.get("Volumes") or {}):
        volumes.append(str(vol))

    return DockerSuggestions(
        exposed_ports=sorted(set(ports)),
        env=env_list,
        volumes=volumes,
    )


def _run_docker_cli_sync(argv: list[str], timeout: float) -> tuple[int, str]:
    """Run the docker CLI with argv list (no shell). Returns (rc, stdout).
    Returns (-1, '') when docker is missing or the call times out."""
    try:
        r = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            timeout=timeout,
        )
        return r.returncode, r.stdout.decode("utf-8", errors="replace")
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return -1, ""


async def inspect_image(image: str, tag: str, *, pull_first: bool = True) -> DockerSuggestions:
    """Pull (optionally) and inspect a Docker image; parse the result.

    Returns empty suggestions if docker is unavailable, auth fails, or any
    step errors. Never raises — the wizard proceeds without suggestions.
    """
    ref = f"{image}:{tag}" if tag else image
    if pull_first:
        # Pull is best-effort and time-capped; ignore the result.
        await asyncio.to_thread(_run_docker_cli_sync, ["docker", "pull", ref], 60.0)
    rc, raw = await asyncio.to_thread(
        _run_docker_cli_sync, ["docker", "image", "inspect", ref], 10.0,
    )
    if rc != 0:
        return DockerSuggestions()
    return parse_docker_inspect(raw)
