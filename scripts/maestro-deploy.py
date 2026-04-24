#!/usr/bin/env python3
"""Client-side deployer for Maestro.

Reads a deployment.yaml, resolves local references in config.templates and
config.files (paths relative to the YAML file), bundles them into the
template_store and files_store fields of the /api/config/apply body, and
POSTs to the Maestro control plane.

Usage:
  scripts/maestro-deploy.py --yaml examples/playmaestro-cloud/deployment.yaml \
                            --cp http://109.199.123.26:8000

Flags:
  --dry-run        include ?dry_run=true in the URL
  --timeout-sec N  HTTP timeout (default 300)
"""
from __future__ import annotations
import argparse
import base64
import io
import json
import os
import sys
import tarfile
import urllib.request
from pathlib import Path

import yaml


def _bundle_to_tar_b64(source_path: Path) -> str:
    """Deterministic tar of a file or directory → base64 string."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tf:
        if source_path.is_file():
            info = tf.gettarinfo(str(source_path), arcname=source_path.name)
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            with source_path.open("rb") as f:
                tf.addfile(info, f)
        else:
            for root, dirs, files in os.walk(source_path):
                dirs.sort()
                files.sort()
                rel_root = Path(root).relative_to(source_path)
                for fname in files:
                    fp = Path(root) / fname
                    arcname = str(rel_root / fname) if str(rel_root) != "." else fname
                    arcname = arcname.replace(os.sep, "/")
                    info = tf.gettarinfo(str(fp), arcname=arcname)
                    info.mtime = 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    with fp.open("rb") as f:
                        tf.addfile(info, f)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _collect_materials(yaml_path: Path) -> tuple[str, dict[str, str], dict[str, str]]:
    yaml_text = yaml_path.read_text(encoding="utf-8")
    spec = yaml.safe_load(yaml_text)
    yaml_dir = yaml_path.parent

    template_store: dict[str, str] = {}
    files_store: dict[str, str] = {}

    for cid, comp in (spec.get("components") or {}).items():
        cfg = comp.get("config") or {}
        for t in cfg.get("templates") or []:
            src = t.get("source")
            if not src:
                continue
            p = (yaml_dir / src).resolve()
            if p.exists() and p.is_file():
                template_store[src] = p.read_text(encoding="utf-8")
        for f in cfg.get("files") or []:
            src = f.get("source")
            if not src:
                continue
            p = (yaml_dir / src).resolve()
            if not p.exists():
                raise FileNotFoundError(f"config.files source not found: {p}")
            files_store[src] = _bundle_to_tar_b64(p)

    return yaml_text, template_store, files_store


def main() -> int:
    ap = argparse.ArgumentParser(description="Maestro deploy client")
    ap.add_argument("--yaml", required=True, help="path to deployment.yaml")
    ap.add_argument("--cp", required=True, help="CP base URL, e.g. http://host:8000")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--timeout-sec", type=int, default=300)
    args = ap.parse_args()

    yaml_path = Path(args.yaml).resolve()
    yaml_text, template_store, files_store = _collect_materials(yaml_path)

    body = json.dumps({
        "yaml_text": yaml_text,
        "template_store": template_store,
        "files_store": files_store,
    }).encode("utf-8")

    url = f"{args.cp.rstrip('/')}/api/config/apply"
    if args.dry_run:
        url += "?dry_run=true"
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=args.timeout_sec) as resp:
            payload = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        sys.stderr.write(f"HTTP {e.code}: {e.read().decode()}\n")
        return 2

    result = json.loads(payload)
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") is not False else 1


if __name__ == "__main__":
    sys.exit(main())
