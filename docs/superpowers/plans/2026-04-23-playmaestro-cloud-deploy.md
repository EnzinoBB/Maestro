# playmaestro.cloud Deploy — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `https://www.playmaestro.cloud/` served from the `website/` directory via Maestro-managed Caddy-in-Docker, while introducing the generic `config.files` primitive (with `atomic_symlink` strategy) and the `reload_triggers.content` key that the use case requires.

**Architecture:** Extend CP Pydantic schema to accept `config.files[]` and `reload_triggers.content`; extend CP renderer to tar-bundle directories and include content hashes in the `request.deploy` payload; refactor the daemon's `writeConfigFiles` helper into a shared module that both systemd and docker runners call, and add archive materialization with three strategies (`overwrite`, `atomic`, `atomic_symlink`). Surface a client script (`scripts/maestro-deploy.py`) that resolves template and file references on the client side and POSTs the bundle to `/api/config/apply`. Example files land under `examples/playmaestro-cloud/`.

**Tech Stack:**
- Control plane: Python 3.11, FastAPI, Pydantic v2, Jinja2, pytest
- Daemon: Go 1.22, stdlib `archive/tar`, `encoding/base64`, `os/exec`
- Deploy target: Ubuntu 24.04, Docker, Caddy 2
- Protocol: WebSocket JSON (control plane ↔ daemon), HTTP REST (client ↔ CP)

---

## Pre-flight

### Task 0: Create worktree and verify environment

**Files:** none (setup)

- [ ] **Step 0.1: Create worktree for this feature**

Run:
```bash
git worktree add ../maestro-playmaestro-deploy -b feature/playmaestro-cloud-deploy
cd ../maestro-playmaestro-deploy
```

- [ ] **Step 0.2: Verify Python and Go toolchains**

Run:
```bash
python3 --version   # expect 3.11+
go version          # expect go1.22+
make test-unit      # baseline: all existing tests pass
```

Expected: existing tests all green (CP pytest + daemon `go test ./...`).

- [ ] **Step 0.3: Confirm host1 reachability**

Run:
```bash
sshpass -p Agent01.2026 ssh -o StrictHostKeyChecking=no agent@109.199.123.26 'docker --version && id agent && curl -s http://127.0.0.1:8000/api/healthz'
```

Expected: docker version string, `id` output showing groups (check whether `docker` group already present), and `{"ok":true}` from CP.

If `sshpass` is not available on Windows, use `plink -pw Agent01.2026` (PuTTY) or a Python one-liner with `paramiko`.

---

## Phase A: CP — Pydantic schema for `config.files` and `reload_triggers.content`

### Task A1: Extend `ReloadTriggers` with `content` field

**Files:**
- Modify: `control-plane/app/config/schema.py:138-141`
- Test: `control-plane/tests/unit/test_config_parser.py` (append new test)

- [ ] **Step A1.1: Write failing test**

Add to `control-plane/tests/unit/test_config_parser.py`:
```python
def test_reload_triggers_accepts_content_key():
    from app.config.loader import parse_deployment
    yaml_text = """
api_version: maestro/v1
project: t
hosts:
  h: {type: linux, address: 1.2.3.4}
components:
  c:
    source: {type: docker, image: nginx}
    run: {type: docker}
    reload_triggers: {code: cold, config: hot, content: hot}
deployment:
  - host: h
    components: [c]
"""
    spec = parse_deployment(yaml_text)
    assert spec.components["c"].reload_triggers.content == "hot"
```

- [ ] **Step A1.2: Run test, verify FAIL**

Run: `cd control-plane && python -m pytest tests/unit/test_config_parser.py::test_reload_triggers_accepts_content_key -v`

Expected: FAIL with Pydantic validation error (`content` field not defined).

- [ ] **Step A1.3: Add `content` to `ReloadTriggers`**

Edit `control-plane/app/config/schema.py` lines 138-141 — the `ReloadTriggers` class:
```python
class ReloadTriggers(_Base):
    code: Literal["hot", "cold"] = "cold"
    config: Literal["hot", "cold"] = "cold"
    dependencies: Literal["hot", "cold"] = "cold"
    content: Literal["hot", "cold"] = "cold"
```

- [ ] **Step A1.4: Run test, verify PASS**

Run: `cd control-plane && python -m pytest tests/unit/test_config_parser.py::test_reload_triggers_accepts_content_key -v`

Expected: PASS.

- [ ] **Step A1.5: Commit**

```bash
git add control-plane/app/config/schema.py control-plane/tests/unit/test_config_parser.py
git commit -m "feat(cp): add reload_triggers.content key to schema"
```

### Task A2: Add `ConfigFile` Pydantic model and `ConfigSpec.files` field

**Files:**
- Modify: `control-plane/app/config/schema.py:66-75`
- Test: `control-plane/tests/unit/test_config_parser.py`

- [ ] **Step A2.1: Write failing test for ConfigFile parsing**

Append to `control-plane/tests/unit/test_config_parser.py`:
```python
def test_config_files_parses_with_all_strategies():
    from app.config.loader import parse_deployment
    yaml_text = """
api_version: maestro/v1
project: t
hosts:
  h: {type: linux, address: 1.2.3.4}
components:
  c:
    source: {type: docker, image: nginx}
    run: {type: docker}
    config:
      files:
        - source: ./site
          dest: /var/www/site
          strategy: atomic_symlink
          mode: 0755
        - source: ./singlefile.txt
          dest: /etc/singlefile
          strategy: overwrite
deployment:
  - host: h
    components: [c]
"""
    spec = parse_deployment(yaml_text)
    files = spec.components["c"].config.files
    assert len(files) == 2
    assert files[0].source == "./site"
    assert files[0].dest == "/var/www/site"
    assert files[0].strategy == "atomic_symlink"
    assert files[0].mode == 0o755
    assert files[1].strategy == "overwrite"


def test_config_files_strategy_must_be_valid():
    from app.config.loader import parse_deployment, LoaderError
    yaml_text = """
api_version: maestro/v1
project: t
hosts:
  h: {type: linux, address: 1.2.3.4}
components:
  c:
    source: {type: docker, image: nginx}
    run: {type: docker}
    config:
      files:
        - source: ./x
          dest: /x
          strategy: bogus
deployment:
  - host: h
    components: [c]
"""
    try:
        parse_deployment(yaml_text)
    except LoaderError as e:
        assert "bogus" in str(e).lower() or "strategy" in str(e).lower()
        return
    raise AssertionError("expected LoaderError")
```

- [ ] **Step A2.2: Run tests, verify FAIL**

Run: `cd control-plane && python -m pytest tests/unit/test_config_parser.py::test_config_files_parses_with_all_strategies tests/unit/test_config_parser.py::test_config_files_strategy_must_be_valid -v`

Expected: both FAIL (no `files` field on `ConfigSpec`).

- [ ] **Step A2.3: Add `ConfigFile` class and extend `ConfigSpec`**

In `control-plane/app/config/schema.py` between the existing `ConfigTemplate` class (lines 66-69) and `ConfigSpec` (lines 72-75), add:

```python
class ConfigFile(_Base):
    source: str
    dest: str
    strategy: Literal["overwrite", "atomic", "atomic_symlink"] = "atomic_symlink"
    mode: int = 0o755
    owner: str | None = None
```

Then replace the existing `ConfigSpec` with:

```python
class ConfigSpec(_Base):
    templates: list[ConfigTemplate] = Field(default_factory=list)
    files: list[ConfigFile] = Field(default_factory=list)
    vars: dict[str, Any] = Field(default_factory=dict)
    secrets: dict[str, str] = Field(default_factory=dict)
```

- [ ] **Step A2.4: Run tests, verify PASS**

Run: `cd control-plane && python -m pytest tests/unit/test_config_parser.py -v`

Expected: new tests PASS, existing tests still PASS.

- [ ] **Step A2.5: Commit**

```bash
git add control-plane/app/config/schema.py control-plane/tests/unit/test_config_parser.py
git commit -m "feat(cp): add ConfigFile schema with overwrite/atomic/atomic_symlink strategies"
```

---

## Phase B: CP renderer — bundle `config.files` into archives with deterministic hash

### Task B1: Add `RenderedConfigArchive` dataclass and payload key

**Files:**
- Modify: `control-plane/app/config/renderer.py:14-48`
- Test: `control-plane/tests/unit/test_config_parser.py` (or new file)

- [ ] **Step B1.1: Write failing test**

Create new test file `control-plane/tests/unit/test_renderer_files.py`:
```python
import base64
import io
import tarfile
from app.config.loader import parse_deployment
from app.config.renderer import render_component


def _make_yaml(source_path: str) -> str:
    return f"""
api_version: maestro/v1
project: t
hosts:
  h: {{type: linux, address: 1.2.3.4}}
components:
  c:
    source: {{type: docker, image: nginx}}
    run: {{type: docker}}
    config:
      files:
        - source: {source_path}
          dest: /var/www/site
          strategy: atomic_symlink
          mode: 0755
deployment:
  - host: h
    components: [c]
"""


def test_render_bundles_directory_to_tar_archive(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<h1>hi</h1>")
    (site / "style.css").write_text("body{}")

    spec = parse_deployment(_make_yaml(str(site)))
    rc = render_component(spec, "c", "h")
    archives = rc.to_payload()["config_archives"]
    assert len(archives) == 1
    a = archives[0]
    assert a["dest"] == "/var/www/site"
    assert a["strategy"] == "atomic_symlink"
    assert a["mode"] == 0o755
    # tar_b64 decodes to a valid tar with both files
    data = base64.b64decode(a["tar_b64"])
    tf = tarfile.open(fileobj=io.BytesIO(data), mode="r")
    names = sorted(m.name for m in tf.getmembers() if m.isfile())
    assert names == ["index.html", "style.css"]
    # content_hash is a stable sha256 hex digest
    assert len(a["content_hash"]) == 64
    assert all(c in "0123456789abcdef" for c in a["content_hash"])


def test_render_hash_deterministic_across_calls(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<h1>hi</h1>")

    spec = parse_deployment(_make_yaml(str(site)))
    rc1 = render_component(spec, "c", "h")
    rc2 = render_component(spec, "c", "h")
    h1 = rc1.to_payload()["config_archives"][0]["content_hash"]
    h2 = rc2.to_payload()["config_archives"][0]["content_hash"]
    assert h1 == h2


def test_render_hash_changes_when_content_changes(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<h1>v1</h1>")

    spec = parse_deployment(_make_yaml(str(site)))
    h1 = render_component(spec, "c", "h").to_payload()["config_archives"][0]["content_hash"]

    (site / "index.html").write_text("<h1>v2</h1>")
    h2 = render_component(spec, "c", "h").to_payload()["config_archives"][0]["content_hash"]
    assert h1 != h2
```

- [ ] **Step B1.2: Run tests, verify FAIL**

Run: `cd control-plane && python -m pytest tests/unit/test_renderer_files.py -v`

Expected: FAIL with `KeyError: 'config_archives'` or similar.

- [ ] **Step B1.3: Implement `RenderedConfigArchive` and tar bundling**

Edit `control-plane/app/config/renderer.py`. After the existing `RenderedConfigFile` class (lines 14-22) add:

```python
import hashlib
import io
import os
import tarfile
from pathlib import Path


@dataclass
class RenderedConfigArchive:
    dest: str
    strategy: str
    mode: int
    tar_bytes: bytes
    content_hash: str

    @property
    def tar_b64(self) -> str:
        return base64.b64encode(self.tar_bytes).decode("ascii")


def _bundle_path_to_tar(source_path: str) -> tuple[bytes, str]:
    """Read a file or directory into a deterministic tar archive.
    Returns (tar_bytes, sha256_hex). Deterministic means: sorted entry names,
    mtime=0, uid=gid=0, uname=gname=''. This guarantees identical content →
    identical bytes → identical hash.
    """
    src = Path(source_path).resolve()
    if not src.exists():
        raise RenderError(f"config.files source not found: {source_path}")

    buf = io.BytesIO()
    tf = tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT)
    try:
        if src.is_file():
            info = tf.gettarinfo(str(src), arcname=src.name)
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            with src.open("rb") as f:
                tf.addfile(info, f)
        else:
            # directory: walk sorted
            for root, dirs, files in os.walk(src):
                dirs.sort()
                files.sort()
                rel_root = Path(root).relative_to(src)
                for fname in files:
                    fpath = Path(root) / fname
                    arcname = str(rel_root / fname) if str(rel_root) != "." else fname
                    info = tf.gettarinfo(str(fpath), arcname=arcname)
                    info.mtime = 0
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    with fpath.open("rb") as f:
                        tf.addfile(info, f)
    finally:
        tf.close()

    data = buf.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    return data, digest
```

Then extend `RenderedComponent`. Replace its current definition (lines 25-48) with:

```python
@dataclass
class RenderedComponent:
    component_id: str
    host_id: str
    source: dict[str, Any]
    build_steps: list[dict[str, Any]] = field(default_factory=list)
    config_files: list[RenderedConfigFile] = field(default_factory=list)
    config_archives: list[RenderedConfigArchive] = field(default_factory=list)
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
            "config_archives": [
                {
                    "dest": a.dest,
                    "strategy": a.strategy,
                    "mode": a.mode,
                    "tar_b64": a.tar_b64,
                    "content_hash": a.content_hash,
                }
                for a in self.config_archives
            ],
            "run": self.run,
            "healthcheck": self.healthcheck,
            "secrets": self.secrets,
        }
```

Finally, extend `render_component` (around line 167). After the existing `config_files` loop add:

```python
    # config archives (files)
    config_archives: list[RenderedConfigArchive] = []
    for entry in component.config.files:
        source_path = _render_str(entry.source, ctx)
        # resolve relative to project root (cwd of the CP); client-side script
        # is expected to have placed source where the server can read it, or
        # the server runs in the project directory.
        tar_bytes, digest = _bundle_path_to_tar(source_path)
        config_archives.append(RenderedConfigArchive(
            dest=_render_str(entry.dest, ctx),
            strategy=entry.strategy,
            mode=entry.mode,
            tar_bytes=tar_bytes,
            content_hash=digest,
        ))
```

And update the `return RenderedComponent(...)` at the end to pass `config_archives=config_archives`.

- [ ] **Step B1.4: Run tests, verify PASS**

Run: `cd control-plane && python -m pytest tests/unit/test_renderer_files.py -v`

Expected: all three tests PASS.

- [ ] **Step B1.5: Run full CP test suite**

Run: `cd control-plane && python -m pytest tests/unit -v`

Expected: all existing tests still PASS.

- [ ] **Step B1.6: Commit**

```bash
git add control-plane/app/config/renderer.py control-plane/tests/unit/test_renderer_files.py
git commit -m "feat(cp): render config.files as deterministic tar archives with sha256 hash"
```

---

## Phase C: CP API — accept client-provided template & file stores

The renderer as written reads `config.files[].source` from the filesystem relative to where the CP is running. For a workstation-driven deploy (`scripts/maestro-deploy.py`), we need the client to ship the file material in the POST body. Extend the API.

### Task C1: Extend `/api/config/apply` body to accept `files_store` and `template_store`

**Files:**
- Modify: `control-plane/app/api/router.py:20-33, 95-113`
- Modify: `control-plane/app/orchestrator/engine.py:136-144` (extend `render_all` signature)
- Modify: `control-plane/app/config/renderer.py` (accept inline `files_store`)
- Test: `control-plane/tests/unit/test_api_apply.py` (new file)

- [ ] **Step C1.1: Write failing test**

Create `control-plane/tests/unit/test_api_apply.py`:
```python
import base64
import io
import tarfile
from fastapi.testclient import TestClient
from app.main import app


def _tar_of(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data in sorted(files.items()):
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mtime = 0
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_apply_accepts_files_store_in_body():
    yaml_text = """
api_version: maestro/v1
project: t
hosts:
  h: {type: linux, address: 1.2.3.4}
components:
  c:
    source: {type: docker, image: nginx}
    run: {type: docker}
    config:
      files:
        - source: site
          dest: /var/www/site
          strategy: atomic_symlink
deployment:
  - host: h
    components: [c]
"""
    tar_b64 = base64.b64encode(_tar_of({"index.html": b"<h1>x</h1>"})).decode()
    body = {
        "yaml_text": yaml_text,
        "files_store": {"site": tar_b64},
    }
    with TestClient(app) as client:
        # dry-run so we don't need daemon connection
        r = client.post("/api/config/apply?dry_run=true", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("ok") is not False
```

- [ ] **Step C1.2: Run test, verify FAIL**

Run: `cd control-plane && python -m pytest tests/unit/test_api_apply.py -v`

Expected: FAIL (either `files_store` is ignored and filesystem read fails, or the API rejects unknown field).

- [ ] **Step C1.3: Extend `_read_yaml_body` to return full body**

In `control-plane/app/api/router.py`, replace `_read_yaml_body` (lines 20-33) with:

```python
async def _read_apply_body(request: Request) -> tuple[str, dict[str, str], dict[str, str]]:
    """Return (yaml_text, template_store, files_store).

    Accepts JSON {yaml_text: ..., template_store?: {name:content}, files_store?: {source:tar_b64}}
    or raw yaml/text body (with empty stores)."""
    ct = (request.headers.get("content-type") or "").split(";")[0].strip()
    raw = await request.body()
    if ct == "application/json":
        import json as _json
        try:
            data = _json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            raise HTTPException(status_code=400, detail="invalid JSON body")
        if not isinstance(data, dict) or "yaml_text" not in data:
            raise HTTPException(status_code=400, detail="JSON body must include 'yaml_text'")
        ts = data.get("template_store") or {}
        fs = data.get("files_store") or {}
        if not isinstance(ts, dict) or not isinstance(fs, dict):
            raise HTTPException(status_code=400, detail="template_store and files_store must be objects")
        return str(data["yaml_text"]), {k: str(v) for k, v in ts.items()}, {k: str(v) for k, v in fs.items()}
    return raw.decode("utf-8", errors="replace"), {}, {}
```

And keep the old name as an alias for backward compatibility with `/api/config/validate` and `/api/config/diff`:

```python
async def _read_yaml_body(request: Request) -> str:
    y, _, _ = await _read_apply_body(request)
    return y
```

- [ ] **Step C1.4: Pass stores through to engine**

In `control-plane/app/api/router.py`, replace `post_apply` (lines 95-113) with:

```python
@router.post("/config/apply")
async def post_apply(request: Request):
    yaml_text, template_store, files_store = await _read_apply_body(request)
    dry_run = request.query_params.get("dry_run", "false").lower() == "true"
    try:
        spec = parse_deployment(yaml_text)
    except LoaderError as e:
        raise HTTPException(status_code=400, detail=str(e))
    errs = semantic_validate(spec)
    if errs:
        raise HTTPException(status_code=400, detail=[e.to_dict() for e in errs])
    engine: Engine = request.app.state.engine
    storage = request.app.state.storage
    if not dry_run:
        await storage.save_config(spec.project, yaml_text)
    result = await engine.apply(spec, dry_run=dry_run,
                                template_store=template_store, files_store=files_store)
    if not dry_run:
        await storage.record_deploy(spec.project, result.ok, result.to_dict())
    return result.to_dict()
```

- [ ] **Step C1.5: Thread stores through `Engine.apply` and `render_all`**

In `control-plane/app/orchestrator/engine.py`:

- Add `template_store` and `files_store` parameters (both `dict[str, str] | None = None`) to `Engine.apply`, `Engine.diff`, and `Engine.render_all`.
- Pass them to `render_component(spec, cid, hid, template_store=..., files_store=...)`.

- [ ] **Step C1.6: Accept `files_store` in renderer**

In `control-plane/app/config/renderer.py`:

- Add `files_store: dict[str, str] | None = None` parameter to `render_component`.
- In the `config.files` loop, instead of calling `_bundle_path_to_tar` directly, first check `files_store`:

```python
    config_archives: list[RenderedConfigArchive] = []
    for entry in component.config.files:
        source_key = _render_str(entry.source, ctx)
        if files_store and source_key in files_store:
            tar_bytes = base64.b64decode(files_store[source_key])
            digest = hashlib.sha256(tar_bytes).hexdigest()
        else:
            tar_bytes, digest = _bundle_path_to_tar(source_key)
        config_archives.append(RenderedConfigArchive(
            dest=_render_str(entry.dest, ctx),
            strategy=entry.strategy,
            mode=entry.mode,
            tar_bytes=tar_bytes,
            content_hash=digest,
        ))
```

- [ ] **Step C1.7: Run test, verify PASS**

Run: `cd control-plane && python -m pytest tests/unit/test_api_apply.py -v`

Expected: PASS.

- [ ] **Step C1.8: Run full CP suite**

Run: `cd control-plane && python -m pytest tests/unit -v`

Expected: all PASS.

- [ ] **Step C1.9: Commit**

```bash
git add control-plane/app/api/router.py control-plane/app/orchestrator/engine.py \
        control-plane/app/config/renderer.py control-plane/tests/unit/test_api_apply.py
git commit -m "feat(cp): accept files_store and template_store in /api/config/apply body"
```

---

## Phase D: Daemon — shared `materialize` module with three strategies

### Task D1: Move `writeConfigFiles` out of `systemd.go` into shared file

**Files:**
- Create: `daemon/internal/runner/materialize.go`
- Modify: `daemon/internal/runner/systemd.go:159-184`

- [ ] **Step D1.1: Create `materialize.go` with the moved function**

Create `daemon/internal/runner/materialize.go`:
```go
package runner

import (
	"encoding/base64"
	"fmt"
	"os"
	"path/filepath"
)

// WriteConfigFiles materializes simple base64-encoded single files to disk.
// Used for config.templates rendered by the CP. Each file is written with
// os.WriteFile (non-atomic); for atomic semantics use MaterializeArchive.
func WriteConfigFiles(baseDir string, files []ConfigFile) error {
	for _, f := range files {
		dest := f.Dest
		if dest == "" {
			continue
		}
		if !filepath.IsAbs(dest) {
			dest = filepath.Join(baseDir, dest)
		}
		if err := os.MkdirAll(filepath.Dir(dest), 0o755); err != nil {
			return fmt.Errorf("mkdir %s: %w", filepath.Dir(dest), err)
		}
		data, err := base64.StdEncoding.DecodeString(f.ContentB64)
		if err != nil {
			return fmt.Errorf("decode %s: %w", dest, err)
		}
		mode := os.FileMode(f.Mode)
		if mode == 0 {
			mode = 0o640
		}
		if err := os.WriteFile(dest, data, mode); err != nil {
			return fmt.Errorf("write %s: %w", dest, err)
		}
	}
	return nil
}
```

- [ ] **Step D1.2: Remove old private `writeConfigFiles` from `systemd.go`**

Delete lines 159-184 of `daemon/internal/runner/systemd.go` (the `writeConfigFiles` function).

- [ ] **Step D1.3: Update caller in `systemd.go`**

Change line 199 from:
```go
if err := writeConfigFiles(dir, d.ConfigFiles); err != nil {
```
to:
```go
if err := WriteConfigFiles(dir, d.ConfigFiles); err != nil {
```

- [ ] **Step D1.4: Run tests, verify existing PASS**

Run: `cd daemon && CGO_ENABLED=0 go test ./...`

Expected: all tests PASS (the existing `TestWriteConfigFilesBadBase64` should still work — may need to rename to `TestWriteConfigFilesBadBase64` calling exported `WriteConfigFiles`).

- [ ] **Step D1.5: Fix the existing test if it referenced unexported name**

In `daemon/internal/runner/systemd_test.go` around line 45, update any reference from `writeConfigFiles` to `WriteConfigFiles`.

- [ ] **Step D1.6: Run tests again, verify PASS**

Run: `cd daemon && CGO_ENABLED=0 go test ./...`

Expected: PASS.

- [ ] **Step D1.7: Commit**

```bash
git add daemon/internal/runner/materialize.go daemon/internal/runner/systemd.go \
        daemon/internal/runner/systemd_test.go
git commit -m "refactor(daemon): move writeConfigFiles to shared runner/materialize.go"
```

### Task D2: Add `ConfigArchive` struct and `ComponentDeploy.ConfigArchives` field

**Files:**
- Modify: `daemon/internal/runner/runner.go:10-35`

- [ ] **Step D2.1: Add struct**

In `daemon/internal/runner/runner.go`, after the existing `ConfigFile` struct (around line 35) add:

```go
// ConfigArchive is a tar archive destined for a host path, with a strategy
// governing how it gets materialized (overwrite, atomic, atomic_symlink).
type ConfigArchive struct {
	Dest        string `json:"dest"`
	Strategy    string `json:"strategy"` // "overwrite" | "atomic" | "atomic_symlink"
	Mode        int    `json:"mode"`
	TarB64      string `json:"tar_b64"`
	ContentHash string `json:"content_hash"` // sha256 hex of tar bytes
}
```

And extend `ComponentDeploy` — add field alongside `ConfigFiles`:

```go
type ComponentDeploy struct {
	// ... existing fields ...
	ConfigFiles    []ConfigFile    `json:"config_files"`
	ConfigArchives []ConfigArchive `json:"config_archives"`
	// ... existing fields ...
}
```

- [ ] **Step D2.2: Verify it compiles**

Run: `cd daemon && go build ./...`

Expected: no errors.

- [ ] **Step D2.3: Commit**

```bash
git add daemon/internal/runner/runner.go
git commit -m "feat(daemon): add ConfigArchive struct to ComponentDeploy"
```

### Task D3: Implement archive materialization with three strategies

**Files:**
- Modify: `daemon/internal/runner/materialize.go`
- Test: `daemon/internal/runner/materialize_test.go` (new)

- [ ] **Step D3.1: Write failing tests**

Create `daemon/internal/runner/materialize_test.go`:
```go
package runner

import (
	"archive/tar"
	"bytes"
	"encoding/base64"
	"os"
	"path/filepath"
	"testing"
)

func tarOf(files map[string]string) string {
	var buf bytes.Buffer
	tw := tar.NewWriter(&buf)
	for name, content := range files {
		_ = tw.WriteHeader(&tar.Header{Name: name, Mode: 0644, Size: int64(len(content))})
		_, _ = tw.Write([]byte(content))
	}
	_ = tw.Close()
	return base64.StdEncoding.EncodeToString(buf.Bytes())
}

func TestMaterializeArchiveOverwrite(t *testing.T) {
	dir := t.TempDir()
	arc := ConfigArchive{
		Dest: filepath.Join(dir, "site"), Strategy: "overwrite", Mode: 0o755,
		TarB64: tarOf(map[string]string{"index.html": "<h1>hi</h1>"}),
		ContentHash: "deadbeef",
	}
	if err := MaterializeArchive(arc); err != nil {
		t.Fatalf("MaterializeArchive: %v", err)
	}
	b, err := os.ReadFile(filepath.Join(dir, "site", "index.html"))
	if err != nil || string(b) != "<h1>hi</h1>" {
		t.Fatalf("content mismatch: %v %q", err, string(b))
	}
}

func TestMaterializeArchiveAtomicSymlink(t *testing.T) {
	dir := t.TempDir()
	dest := filepath.Join(dir, "site")
	// first deploy
	arc1 := ConfigArchive{
		Dest: dest, Strategy: "atomic_symlink", Mode: 0o755,
		TarB64: tarOf(map[string]string{"index.html": "v1"}),
		ContentHash: "aaa",
	}
	if err := MaterializeArchive(arc1); err != nil {
		t.Fatal(err)
	}
	// current symlink must point to releases/aaa
	target, err := os.Readlink(filepath.Join(dest, "current"))
	if err != nil {
		t.Fatalf("readlink: %v", err)
	}
	if filepath.Base(target) != "aaa" {
		t.Fatalf("expected current → releases/aaa, got %s", target)
	}
	// content via symlink
	b, _ := os.ReadFile(filepath.Join(dest, "current", "index.html"))
	if string(b) != "v1" {
		t.Fatalf("v1 content mismatch: %q", string(b))
	}
	// second deploy, different hash
	arc2 := ConfigArchive{
		Dest: dest, Strategy: "atomic_symlink", Mode: 0o755,
		TarB64: tarOf(map[string]string{"index.html": "v2"}),
		ContentHash: "bbb",
	}
	if err := MaterializeArchive(arc2); err != nil {
		t.Fatal(err)
	}
	target, _ = os.Readlink(filepath.Join(dest, "current"))
	if filepath.Base(target) != "bbb" {
		t.Fatalf("expected current → releases/bbb, got %s", target)
	}
	b, _ = os.ReadFile(filepath.Join(dest, "current", "index.html"))
	if string(b) != "v2" {
		t.Fatalf("v2 content mismatch")
	}
	// releases/aaa still exists (for rollback)
	if _, err := os.Stat(filepath.Join(dest, "releases", "aaa")); err != nil {
		t.Fatalf("releases/aaa should still exist: %v", err)
	}
}

func TestMaterializeArchiveIdempotent(t *testing.T) {
	dir := t.TempDir()
	dest := filepath.Join(dir, "site")
	arc := ConfigArchive{
		Dest: dest, Strategy: "atomic_symlink", Mode: 0o755,
		TarB64: tarOf(map[string]string{"x": "y"}),
		ContentHash: "samehash",
	}
	if err := MaterializeArchive(arc); err != nil {
		t.Fatal(err)
	}
	// second call with same hash: should be a no-op (not re-extract)
	if err := MaterializeArchive(arc); err != nil {
		t.Fatal(err)
	}
	// current symlink still points to samehash
	target, _ := os.Readlink(filepath.Join(dest, "current"))
	if filepath.Base(target) != "samehash" {
		t.Fatalf("idempotent failed: %s", target)
	}
}

func TestMaterializeArchiveRetainsMaxFive(t *testing.T) {
	dir := t.TempDir()
	dest := filepath.Join(dir, "site")
	for i, h := range []string{"h1", "h2", "h3", "h4", "h5", "h6", "h7"} {
		arc := ConfigArchive{
			Dest: dest, Strategy: "atomic_symlink", Mode: 0o755,
			TarB64: tarOf(map[string]string{"v": string(rune('a'+i))}),
			ContentHash: h,
		}
		if err := MaterializeArchive(arc); err != nil {
			t.Fatalf("deploy %s: %v", h, err)
		}
	}
	entries, _ := os.ReadDir(filepath.Join(dest, "releases"))
	if len(entries) != 5 {
		t.Fatalf("expected 5 releases retained, got %d: %v", len(entries), entries)
	}
	// oldest two (h1, h2) should be gone
	for _, old := range []string{"h1", "h2"} {
		if _, err := os.Stat(filepath.Join(dest, "releases", old)); err == nil {
			t.Fatalf("expected %s to be GC'd", old)
		}
	}
}
```

- [ ] **Step D3.2: Run tests, verify FAIL**

Run: `cd daemon && CGO_ENABLED=0 go test ./internal/runner -run TestMaterializeArchive -v`

Expected: FAIL with "undefined: MaterializeArchive".

- [ ] **Step D3.3: Implement `MaterializeArchive`**

Append to `daemon/internal/runner/materialize.go`:

```go
import (
	"archive/tar"
	"bytes"
	"errors"
	"io"
	"sort"
	"time"
)

const defaultRetainReleases = 5

// MaterializeArchive extracts a ConfigArchive onto the host filesystem
// according to its Strategy. For atomic_symlink it writes to
// <Dest>/releases/<ContentHash>/, flips <Dest>/current → releases/<hash>,
// and GCs older releases to defaultRetainReleases entries.
func MaterializeArchive(arc ConfigArchive) error {
	if arc.Dest == "" {
		return errors.New("archive Dest is required")
	}
	tarBytes, err := base64.StdEncoding.DecodeString(arc.TarB64)
	if err != nil {
		return fmt.Errorf("decode tar_b64: %w", err)
	}

	switch arc.Strategy {
	case "overwrite":
		return extractTar(tarBytes, arc.Dest, os.FileMode(effectiveMode(arc.Mode)))
	case "atomic":
		tmp := arc.Dest + ".tmp"
		_ = os.RemoveAll(tmp)
		if err := extractTar(tarBytes, tmp, os.FileMode(effectiveMode(arc.Mode))); err != nil {
			return err
		}
		// remove the old dest then rename the tmp
		_ = os.RemoveAll(arc.Dest)
		return os.Rename(tmp, arc.Dest)
	case "atomic_symlink", "":
		return materializeAtomicSymlink(arc.Dest, arc.ContentHash, tarBytes, os.FileMode(effectiveMode(arc.Mode)))
	default:
		return fmt.Errorf("unsupported strategy: %s", arc.Strategy)
	}
}

func effectiveMode(m int) int {
	if m == 0 {
		return 0o755
	}
	return m
}

func materializeAtomicSymlink(dest, hash string, tarBytes []byte, mode os.FileMode) error {
	if hash == "" {
		return errors.New("atomic_symlink requires ContentHash")
	}
	releasesDir := filepath.Join(dest, "releases")
	if err := os.MkdirAll(releasesDir, mode); err != nil {
		return fmt.Errorf("mkdir releases: %w", err)
	}
	releasePath := filepath.Join(releasesDir, hash)
	currentLink := filepath.Join(dest, "current")

	// Idempotency: if release already exists AND current points to it, no-op.
	if fi, err := os.Stat(releasePath); err == nil && fi.IsDir() {
		if target, lerr := os.Readlink(currentLink); lerr == nil && filepath.Base(target) == hash {
			return nil
		}
	} else {
		// extract fresh
		if err := extractTar(tarBytes, releasePath, mode); err != nil {
			return err
		}
	}

	// Atomic flip: symlink write to <dest>/current.tmp then rename.
	// On Linux/macOS, os.Symlink + os.Rename is atomic w.r.t. readers.
	tmpLink := filepath.Join(dest, "current.tmp")
	_ = os.Remove(tmpLink)
	relTarget := filepath.Join("releases", hash)
	if err := os.Symlink(relTarget, tmpLink); err != nil {
		return fmt.Errorf("symlink tmp: %w", err)
	}
	if err := os.Rename(tmpLink, currentLink); err != nil {
		return fmt.Errorf("rename current: %w", err)
	}

	return gcOldReleases(releasesDir, defaultRetainReleases)
}

func extractTar(tarBytes []byte, dest string, mode os.FileMode) error {
	if err := os.MkdirAll(dest, mode); err != nil {
		return fmt.Errorf("mkdir dest: %w", err)
	}
	tr := tar.NewReader(bytes.NewReader(tarBytes))
	for {
		hdr, err := tr.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return fmt.Errorf("tar next: %w", err)
		}
		// security: reject absolute or .. paths
		cleaned := filepath.Clean(hdr.Name)
		if filepath.IsAbs(cleaned) || cleaned == ".." || len(cleaned) >= 2 && cleaned[:2] == ".." {
			return fmt.Errorf("unsafe tar entry: %s", hdr.Name)
		}
		target := filepath.Join(dest, cleaned)
		switch hdr.Typeflag {
		case tar.TypeDir:
			if err := os.MkdirAll(target, os.FileMode(hdr.Mode)); err != nil {
				return err
			}
		case tar.TypeReg, tar.TypeRegA:
			if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
				return err
			}
			f, err := os.OpenFile(target, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, os.FileMode(hdr.Mode))
			if err != nil {
				return err
			}
			if _, err := io.Copy(f, tr); err != nil {
				_ = f.Close()
				return err
			}
			_ = f.Close()
		default:
			// skip symlinks and other types for safety in Phase 1
		}
	}
	return nil
}

func gcOldReleases(releasesDir string, retain int) error {
	entries, err := os.ReadDir(releasesDir)
	if err != nil {
		return nil // nothing to GC
	}
	type entInfo struct {
		name string
		mtime time.Time
	}
	infos := []entInfo{}
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		fi, err := os.Stat(filepath.Join(releasesDir, e.Name()))
		if err != nil {
			continue
		}
		infos = append(infos, entInfo{name: e.Name(), mtime: fi.ModTime()})
	}
	if len(infos) <= retain {
		return nil
	}
	sort.Slice(infos, func(i, j int) bool { return infos[i].mtime.Before(infos[j].mtime) })
	toRemove := len(infos) - retain
	for _, inf := range infos[:toRemove] {
		_ = os.RemoveAll(filepath.Join(releasesDir, inf.name))
	}
	return nil
}
```

Note: consolidate the imports at top of the file (merge the existing and new `import` blocks into one).

- [ ] **Step D3.4: Run tests, verify PASS**

Run: `cd daemon && CGO_ENABLED=0 go test ./internal/runner -run TestMaterializeArchive -v`

Expected: all 4 tests PASS.

- [ ] **Step D3.5: Run full daemon suite**

Run: `cd daemon && CGO_ENABLED=0 go test ./...`

Expected: all PASS.

- [ ] **Step D3.6: Commit**

```bash
git add daemon/internal/runner/materialize.go daemon/internal/runner/materialize_test.go
git commit -m "feat(daemon): implement ConfigArchive materialization with 3 strategies"
```

---

## Phase E: Daemon — wire `ConfigArchives` into Docker runner

### Task E1: DockerRunner materializes config files and archives before container start

**Files:**
- Modify: `daemon/internal/runner/docker.go:160-225`
- Test: `daemon/internal/runner/docker_test.go` (new or extend)

- [ ] **Step E1.1: Write failing integration test**

Append to `daemon/internal/runner/docker_test.go` (create if absent):
```go
//go:build integration_docker
// +build integration_docker

package runner

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"
)

// This test requires a local docker socket. Gate it behind a build tag.
func TestDockerDeployWithConfigArchive(t *testing.T) {
	tmp := t.TempDir()
	dest := filepath.Join(tmp, "site")

	dp := &ComponentDeploy{
		ComponentID: "docker-config-test",
		TargetHash:  "t1",
		Run: map[string]any{
			"type": "docker",
			"image": "alpine:3.19",
			"command": []any{"sleep", "1"},
		},
		Source: map[string]any{"image": "alpine", "tag": "3.19", "pull_policy": "if_not_present"},
		ConfigArchives: []ConfigArchive{{
			Dest: dest, Strategy: "atomic_symlink", Mode: 0o755,
			TarB64: tarOf(map[string]string{"index.html": "hello"}),
			ContentHash: "h1",
		}},
	}
	r := NewDockerRunner()
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()
	res, err := r.Deploy(ctx, dp)
	if err != nil || !res.OK {
		t.Fatalf("deploy failed: %v %+v", err, res)
	}
	// verify archive was materialized BEFORE the container started
	b, err := os.ReadFile(filepath.Join(dest, "current", "index.html"))
	if err != nil || string(b) != "hello" {
		t.Fatalf("materialize failed: %v %q", err, string(b))
	}
	_ = r.Stop(ctx, dp, 5*time.Second)
}
```

- [ ] **Step E1.2: Add config phase to `DockerRunner.Deploy`**

Edit `daemon/internal/runner/docker.go`. In the `Deploy` method, after the existing `fetch` phase (around line 201) and BEFORE `stop old` (line 203), insert a config phase:

```go
	// config phase: write ConfigFiles and materialize ConfigArchives
	cp := time.Now()
	baseDir := filepath.Join(os.TempDir(), "maestro", dp.ComponentID)
	if err := os.MkdirAll(baseDir, 0o755); err != nil {
		phases = append(phases, PhaseResult{Name: "config", OK: false,
			DurationMS: time.Since(cp).Milliseconds(), Detail: err.Error()})
		return &DeployResult{OK: false, ComponentID: dp.ComponentID, Phases: phases,
			Error: &ErrorInfo{Code: "config_error", Phase: "config", Message: err.Error()}}, nil
	}
	if err := WriteConfigFiles(baseDir, dp.ConfigFiles); err != nil {
		phases = append(phases, PhaseResult{Name: "config", OK: false,
			DurationMS: time.Since(cp).Milliseconds(), Detail: err.Error()})
		return &DeployResult{OK: false, ComponentID: dp.ComponentID, Phases: phases,
			Error: &ErrorInfo{Code: "config_error", Phase: "config", Message: err.Error()}}, nil
	}
	for _, arc := range dp.ConfigArchives {
		if err := MaterializeArchive(arc); err != nil {
			phases = append(phases, PhaseResult{Name: "config", OK: false,
				DurationMS: time.Since(cp).Milliseconds(), Detail: err.Error()})
			return &DeployResult{OK: false, ComponentID: dp.ComponentID, Phases: phases,
				Error: &ErrorInfo{Code: "config_error", Phase: "config", Message: err.Error()}}, nil
		}
	}
	phases = append(phases, PhaseResult{Name: "config", OK: true,
		DurationMS: time.Since(cp).Milliseconds()})
```

And add `"os"`, `"path/filepath"` to the imports at the top of `docker.go`.

- [ ] **Step E1.3: Run integration test (requires local docker)**

Run: `cd daemon && CGO_ENABLED=0 go test -tags integration_docker ./internal/runner -run TestDockerDeployWithConfigArchive -v`

Expected: PASS if docker is available locally, otherwise skip.

- [ ] **Step E1.4: Run full daemon suite (non-integration)**

Run: `cd daemon && CGO_ENABLED=0 go test ./...`

Expected: all PASS.

- [ ] **Step E1.5: Commit**

```bash
git add daemon/internal/runner/docker.go daemon/internal/runner/docker_test.go
git commit -m "feat(daemon): materialize ConfigFiles and ConfigArchives in DockerRunner"
```

### Task E2: Also hook ConfigArchives into SystemdRunner

**Files:**
- Modify: `daemon/internal/runner/systemd.go:198-204`

- [ ] **Step E2.1: Add archive materialization after config files**

In `systemd.go`, right after the `WriteConfigFiles` call (around line 204), add:

```go
	for _, arc := range d.ConfigArchives {
		if err := MaterializeArchive(arc); err != nil {
			phases = append(phases, PhaseResult{Name: "config", OK: false,
				DurationMS: time.Since(cp).Milliseconds(), Detail: err.Error()})
			return &DeployResult{OK: false, ComponentID: d.ComponentID, Phases: phases,
				Error: &ErrorInfo{Code: "config_error", Phase: "config", Message: err.Error()}}, nil
		}
	}
```

(Keep this inside the existing `cp := time.Now()` phase block — same timing bucket as WriteConfigFiles.)

- [ ] **Step E2.2: Run tests**

Run: `cd daemon && CGO_ENABLED=0 go test ./...`

Expected: all PASS.

- [ ] **Step E2.3: Commit**

```bash
git add daemon/internal/runner/systemd.go
git commit -m "feat(daemon): materialize ConfigArchives in SystemdRunner"
```

---

## Phase F: Protocol and schema documentation

### Task F1: Update `docs/protocol.md` and `docs/yaml-schema.md`

**Files:**
- Modify: `docs/protocol.md:157-168` (request.deploy payload)
- Modify: `docs/yaml-schema.md:134-151` (config section)

- [ ] **Step F1.1: Update `docs/protocol.md` `request.deploy` payload**

In the payload JSON example (around line 160), add a `config_archives` field after `config_files`:

```json
"config_archives": [
  {
    "dest": "/var/www/site",
    "strategy": "atomic_symlink",
    "mode": 493,
    "tar_b64": "H4sIA...",
    "content_hash": "a1b2..."
  }
]
```

And add a paragraph after the `config_files` description:

> `config_archives` carries tar-bundled directory material. Each entry has a
> strategy (`overwrite`, `atomic`, `atomic_symlink`) that determines how the
> daemon materializes it on the host. For `atomic_symlink` the daemon keeps
> the last 5 releases under `<dest>/releases/<content_hash>/` and flips
> `<dest>/current` atomically.

- [ ] **Step F1.2: Update `docs/yaml-schema.md` `config` section**

In the `### config` subsection (lines 134-151), append:

```yaml
config:
  templates:
    - source: configs/api.env.j2
      dest: /etc/my-app/api.env
      mode: 0640
  files:
    - source: ./assets            # directory or single file
      dest: /var/www/assets
      strategy: atomic_symlink    # overwrite | atomic | atomic_symlink
      mode: 0755
```

Followed by a paragraph:

> `config.files` materializes verbatim files or directories (no Jinja2
> rendering) on the target host. Three strategies:
> - `overwrite` — direct copy, non-atomic.
> - `atomic` — write to `.tmp` + rename, atomic per path.
> - `atomic_symlink` — extract to `<dest>/releases/<hash>/` and flip
>   `<dest>/current`. Zero-downtime; rollback via `request.rollback` flips
>   back to the previous release. Default strategy for directory sources.

And update the `reload_triggers` subsection to include `content`:

```yaml
reload_triggers:
  code: cold
  config: hot
  dependencies: cold
  content: hot                   # fires when a config.files entry changes
```

- [ ] **Step F1.3: Commit**

```bash
git add docs/protocol.md docs/yaml-schema.md
git commit -m "docs: document config.files primitive and reload_triggers.content"
```

---

## Phase G: Client script `scripts/maestro-deploy.py`

### Task G1: Create the deploy client

**Files:**
- Create: `scripts/maestro-deploy.py`
- Modify: `scripts/maestrod-config.example.yaml` (unrelated, skip)

- [ ] **Step G1.1: Create the script**

Create `scripts/maestro-deploy.py`:

```python
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
```

- [ ] **Step G1.2: Make executable and smoke test**

Run:
```bash
chmod +x scripts/maestro-deploy.py
python3 scripts/maestro-deploy.py --help
```

Expected: help text printed, exit 0.

- [ ] **Step G1.3: Commit**

```bash
git add scripts/maestro-deploy.py
git commit -m "feat(scripts): add maestro-deploy.py client that bundles templates and files"
```

---

## Phase H: Example files

### Task H1: Create `examples/playmaestro-cloud/`

**Files:**
- Create: `examples/playmaestro-cloud/deployment.yaml`
- Create: `examples/playmaestro-cloud/Caddyfile.j2`
- Create: `examples/playmaestro-cloud/README.md`

- [ ] **Step H1.1: Create `deployment.yaml`**

Create `examples/playmaestro-cloud/deployment.yaml`:
```yaml
api_version: maestro/v1
project: playmaestro-cloud
description: Static website www.playmaestro.cloud served by Caddy with automatic Let's Encrypt HTTPS

hosts:
  host1:
    type: linux
    address: 109.199.123.26
    user: agent
    tags: [prod, web]

components:
  caddy-playmaestro:
    description: Caddy reverse proxy + static file server with auto-HTTPS
    source:
      type: docker
      image: caddy
      tag: "2-alpine"
      pull_policy: if_not_present
    config:
      templates:
        - source: Caddyfile.j2
          dest: /home/agent/playmaestro/caddy/Caddyfile
          mode: 0644
      files:
        - source: ../../website
          dest: /home/agent/playmaestro/site
          strategy: atomic_symlink
          mode: 0755
      vars:
        primary_host: www.playmaestro.cloud
        apex_host: playmaestro.cloud
    run:
      type: docker
      container_name: caddy-playmaestro
      image: "{{ source.image }}:{{ source.tag }}"
      ports:
        - "80:80"
        - "443:443"
      volumes:
        - "/home/agent/playmaestro/site:/srv-root:ro"
        - "/home/agent/playmaestro/caddy/data:/data"
        - "/home/agent/playmaestro/caddy/Caddyfile:/etc/caddy/Caddyfile:ro"
      restart: unless-stopped
    deploy_mode: hot
    reload_triggers:
      code: cold
      config: hot
      content: hot
    healthcheck:
      type: http
      url: https://www.playmaestro.cloud/
      expect_status: 200
      interval: 30s
      timeout: 10s
      start_period: 60s
      retries: 3

deployment:
  - host: host1
    components: [caddy-playmaestro]
    strategy: sequential
```

- [ ] **Step H1.2: Create `Caddyfile.j2`**

Create `examples/playmaestro-cloud/Caddyfile.j2`:
```caddy
{{ vars.primary_host }} {
    root * /srv-root/current
    file_server
    encode gzip

    header {
        Strict-Transport-Security "max-age=31536000; includeSubDomains"
        X-Content-Type-Options nosniff
        Referrer-Policy strict-origin-when-cross-origin
    }
}

{{ vars.apex_host }} {
    redir https://{{ vars.primary_host }}{uri} permanent
}
```

- [ ] **Step H1.3: Create `README.md`**

Create `examples/playmaestro-cloud/README.md`:
```markdown
# playmaestro.cloud — Reference deploy

Deploys the root-level `website/` directory as a static site at
`https://www.playmaestro.cloud/`, served by Caddy-in-Docker with automatic
Let's Encrypt HTTPS. This example exercises the `config.files` primitive
(atomic_symlink strategy) and the `reload_triggers.content: hot` key.

## One-time host preparation

See `docs/superpowers/specs/2026-04-23-playmaestro-cloud-deploy-design.md §4`.
Three commands on host1:

```bash
sudo usermod -aG docker agent   # log out/in required
sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
mkdir -p /home/agent/playmaestro/{site/releases,caddy/data}
```

## Deploy

From a workstation, with CP reachable:

```bash
python3 scripts/maestro-deploy.py \
  --yaml examples/playmaestro-cloud/deployment.yaml \
  --cp http://109.199.123.26:8000
```

The client script bundles `Caddyfile.j2` into `template_store` and `website/`
into `files_store` (as a deterministic tar) and POSTs to `/api/config/apply`.

## Rollback

```bash
curl -X POST http://109.199.123.26:8000/api/components/caddy-playmaestro/rollback \
  -H "Content-Type: application/json" -d '{"steps_back": 1}'
```

This re-flips `/home/agent/playmaestro/site/current` to the previous release
under `releases/`. Zero downtime; no container restart required.

## Kill-switch

```bash
ssh agent@109.199.123.26 docker stop caddy-playmaestro
```

Ports 80/443 go unbound. Restore with `docker start caddy-playmaestro`.
```

- [ ] **Step H1.4: Commit**

```bash
git add examples/playmaestro-cloud/
git commit -m "docs(examples): add playmaestro.cloud reference deploy example"
```

---

## Phase I: Deploy CP code updates to host1

The new schema, renderer, and API changes live in the CP code. The CP instance on host1 must be updated before a deploy that uses these features.

### Task I1: Push branch to origin and update host1's CP

**Files:** none (operational)

- [ ] **Step I1.1: Push branch to origin**

Run:
```bash
git push -u origin feature/playmaestro-cloud-deploy
```

Expected: branch pushed.

- [ ] **Step I1.2: SSH into host1 and fetch**

Run:
```bash
sshpass -p Agent01.2026 ssh agent@109.199.123.26 \
  'cd /home/agent/maestro && git fetch origin feature/playmaestro-cloud-deploy && git checkout feature/playmaestro-cloud-deploy'
```

Expected: branch checked out on host1.

Notes:
- If the CP repo path on host1 differs from `/home/agent/maestro`, use the actual path (check with `ls /home/agent/`).
- If the repo was not a git clone but an installer-pushed copy, use `rsync` from workstation instead: `rsync -avz --exclude .git --exclude '*.db' --exclude .venv ./control-plane/ agent@109.199.123.26:/home/agent/maestro/control-plane/`.

- [ ] **Step I1.3: Reinstall CP dependencies and restart uvicorn**

Run:
```bash
sshpass -p Agent01.2026 ssh agent@109.199.123.26 bash -lc '
  cd /home/agent/maestro/control-plane
  .venv/bin/pip install -e . --quiet
  # Find current CP pid (adjust if systemd-managed)
  pkill -f "uvicorn app.main:app" || true
  sleep 1
  cd /home/agent/maestro
  setsid nohup ./control-plane/.venv/bin/python -m uvicorn app.main:app \
    --host 0.0.0.0 --port 8000 --app-dir control-plane \
    > /home/agent/maestro-cp.log 2>&1 < /dev/null &
  sleep 3
  curl -sf http://127.0.0.1:8000/api/healthz
'
```

Expected: `{"ok":true}` at the end.

---

## Phase J: Manual host1 preparation

### Task J1: Verify and apply the one-time prep

**Files:** none

- [ ] **Step J1.1: Check current state**

Run:
```bash
sshpass -p Agent01.2026 ssh agent@109.199.123.26 bash -lc '
  echo "-- id:"; id agent
  echo "-- docker:"; docker --version && docker ps --format "{{.Names}}" | head
  echo "-- ufw:"; sudo ufw status | head
  echo "-- ports 80/443:"; ss -tlnp | grep -E ":80 |:443 " || echo "clear"
'
```

Expected: inspect output. If `docker` is not in `id agent` groups, run step J1.2. If UFW doesn't show 80/443 allowed, run step J1.3.

- [ ] **Step J1.2: Add `agent` to `docker` group (if needed)**

Run:
```bash
sshpass -p Agent01.2026 ssh agent@109.199.123.26 'echo Agent01.2026 | sudo -S usermod -aG docker agent'
```

Expected: no output, exit 0. Then terminate all SSH sessions and re-SSH for the group to take effect:
```bash
sshpass -p Agent01.2026 ssh agent@109.199.123.26 'id agent | grep docker'
```

- [ ] **Step J1.3: Allow ports 80 and 443**

Run:
```bash
sshpass -p Agent01.2026 ssh agent@109.199.123.26 \
  'echo Agent01.2026 | sudo -S ufw allow 80/tcp && echo Agent01.2026 | sudo -S ufw allow 443/tcp && sudo ufw reload'
```

Expected: `Rule added`, `Firewall reloaded`.

- [ ] **Step J1.4: Create playmaestro root directory**

Run:
```bash
sshpass -p Agent01.2026 ssh agent@109.199.123.26 \
  'mkdir -p /home/agent/playmaestro/site/releases /home/agent/playmaestro/caddy/data && ls -la /home/agent/playmaestro/'
```

Expected: two subdirectories `site/` and `caddy/` listed.

- [ ] **Step J1.5: DNS sanity check**

Run:
```bash
dig www.playmaestro.cloud +short
dig playmaestro.cloud +short
```

Expected: both return `109.199.123.26`.

If either fails, STOP and resolve DNS before proceeding — deploys will fail the healthcheck.

---

## Phase K: First deploy

### Task K1: Execute the deploy via the client

**Files:** none

- [ ] **Step K1.1: Run the deploy**

From the worktree:
```bash
python3 scripts/maestro-deploy.py \
  --yaml examples/playmaestro-cloud/deployment.yaml \
  --cp http://109.199.123.26:8000
```

Expected: JSON response with `"ok": true` and phase breakdown showing `fetch`, `config`, `stop_old`, `start`, `health` all `"ok": true`. Note that the `health` phase may take up to 60 s on the first deploy (Let's Encrypt acquisition).

If `health` fails with non-200: check `docker logs caddy-playmaestro` on host1 — most likely Let's Encrypt rate-limited us (use `caddy:2-alpine` staging endpoint for testing if so, then switch back).

- [ ] **Step K1.2: Verify container state on host1**

Run:
```bash
sshpass -p Agent01.2026 ssh agent@109.199.123.26 bash -lc '
  docker ps --filter name=caddy-playmaestro
  ls -la /home/agent/playmaestro/site/
  readlink /home/agent/playmaestro/site/current
  ls /home/agent/playmaestro/caddy/data/caddy/certificates/acme-v02*/ 2>/dev/null || echo "cert not yet issued"
'
```

Expected: container running, `current` symlink pointing to `releases/<hash>/`, cert files present after first HTTPS hit (may need 30-60 s).

### Task K2: Validate per spec §7

**Files:** none

- [ ] **Step K2.1: HTTPS 200 on www**

Run: `curl -sI https://www.playmaestro.cloud/`

Expected: `HTTP/2 200`, `content-type: text/html`, `strict-transport-security: max-age=31536000; includeSubDomains`.

- [ ] **Step K2.2: HTTP redirects to HTTPS**

Run: `curl -sI http://www.playmaestro.cloud/`

Expected: `308` with `Location: https://www.playmaestro.cloud/`.

- [ ] **Step K2.3: apex redirects to www**

Run: `curl -sI https://playmaestro.cloud/`

Expected: `301` with `Location: https://www.playmaestro.cloud/`.

- [ ] **Step K2.4: Cert issued by Let's Encrypt**

Run:
```bash
echo | openssl s_client -connect www.playmaestro.cloud:443 -servername www.playmaestro.cloud 2>/dev/null | openssl x509 -noout -issuer
```

Expected: output contains `O = Let's Encrypt`.

- [ ] **Step K2.5: Body matches `website/index.html`**

Run:
```bash
curl -s https://www.playmaestro.cloud/ | diff - website/index.html
```

Expected: no output (byte-identical).

- [ ] **Step K2.6: Browser check**

Open `https://www.playmaestro.cloud/` in a browser. Confirm green padlock, no mixed-content warnings in devtools console, site renders as expected.

---

## Phase L: Idempotency and rollback verification

### Task L1: Idempotency

**Files:** none

- [ ] **Step L1.1: Re-run the deploy with no changes**

Run:
```bash
python3 scripts/maestro-deploy.py \
  --yaml examples/playmaestro-cloud/deployment.yaml \
  --cp http://109.199.123.26:8000
```

Expected: `"ok": true`. Inspect the phases JSON — the deploy flow runs, but on host1 no new extraction happens (same content hash), the symlink flip is a no-op, and the container is NOT restarted (only hot config reload if Caddyfile changed — with no YAML change, not even that).

- [ ] **Step L1.2: Confirm single release dir on host**

Run:
```bash
sshpass -p Agent01.2026 ssh agent@109.199.123.26 \
  'ls /home/agent/playmaestro/site/releases/ | wc -l'
```

Expected: `1`. (Two identical deploys should not produce two release dirs.)

### Task L2: Content change + rollback

**Files:**
- Modify (temporarily): `website/index.html`

- [ ] **Step L2.1: Modify a character in the site**

Edit `website/index.html` — change any visible text by appending a unique token like `DEPLOY-TEST-001`.

- [ ] **Step L2.2: Redeploy**

Run:
```bash
python3 scripts/maestro-deploy.py \
  --yaml examples/playmaestro-cloud/deployment.yaml \
  --cp http://109.199.123.26:8000
```

Expected: `"ok": true`, new release dir under `releases/`.

- [ ] **Step L2.3: Verify new content is served**

Run:
```bash
curl -s https://www.playmaestro.cloud/ | grep -c DEPLOY-TEST-001
```

Expected: `1`.

- [ ] **Step L2.4: Rollback via CP API**

Run:
```bash
curl -X POST http://109.199.123.26:8000/api/components/caddy-playmaestro/rollback \
  -H "Content-Type: application/json" -d '{"steps_back": 1}'
```

Expected: `{"ok": true, ...}`.

(Note: the `/api/components/{cid}/rollback` endpoint may not yet exist — verify from `control-plane/app/api/router.py`. If absent, achieve the rollback by re-running the deploy against the unmodified YAML and reverting `website/index.html` to its original state.)

- [ ] **Step L2.5: Verify previous content is restored**

Run:
```bash
curl -s https://www.playmaestro.cloud/ | grep -c DEPLOY-TEST-001
```

Expected: `0`.

- [ ] **Step L2.6: Revert local modification**

Run:
```bash
git checkout website/index.html
```

Expected: file back to committed state.

---

## Phase M: Finalization

### Task M1: Documentation polish

**Files:**
- Modify: `examples/playmaestro-cloud/README.md` (add "verified on 2026-04-23" note)
- Modify: `docs/superpowers/specs/2026-04-23-playmaestro-cloud-deploy-design.md` (update Status to "Implemented")

- [ ] **Step M1.1: Mark spec as Implemented**

Change `**Status:** Approved` to `**Status:** Implemented (2026-04-23)` in the spec file header.

- [ ] **Step M1.2: Commit**

```bash
git add examples/playmaestro-cloud/README.md docs/superpowers/specs/2026-04-23-playmaestro-cloud-deploy-design.md
git commit -m "docs: mark playmaestro.cloud deploy spec as implemented"
```

### Task M2: PR

**Files:** none

- [ ] **Step M2.1: Open PR to `main`**

Run:
```bash
gh pr create --title "feat: config.files primitive + playmaestro.cloud reference deploy" --body "$(cat <<'EOF'
## Summary
- Introduces `config.files` with three strategies (`overwrite`, `atomic`, `atomic_symlink`) as a generalization of file-material deploy for any component (spec in `docs/superpowers/specs/2026-04-23-...`).
- Adds `reload_triggers.content: hot|cold` trigger key.
- Wires `ConfigArchives` through CP renderer, WS protocol, daemon docker + systemd runners.
- Ships `examples/playmaestro-cloud/` as reference deploy for `https://www.playmaestro.cloud/`.
- Adds `scripts/maestro-deploy.py` client helper for bundling templates and file material on the client side.

## Test plan
- [x] CP unit tests (`pytest tests/unit`)
- [x] Daemon unit tests (`go test ./...`)
- [x] Daemon integration test `TestDockerDeployWithConfigArchive` (requires docker, tagged `integration_docker`)
- [x] End-to-end deploy against host1 (109.199.123.26) — site live at https://www.playmaestro.cloud/
- [x] Idempotency: re-running the deploy produces no change
- [x] Rollback: previous release restored by symlink flip

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL printed.

---

## Self-Review Notes

**Spec coverage check** (run against `docs/superpowers/specs/2026-04-23-playmaestro-cloud-deploy-design.md`):

| Spec section | Implemented by |
|---|---|
| §1 Context & goals | All phases |
| §2 Architecture overview | Tasks A1-L2 |
| §3.1 `config.files` motivation | N/A (design commentary) |
| §3.2 Schema extension | Task A2 |
| §3.3 Retention & rollback | Task D3 (`defaultRetainReleases=5`), Task L2 (rollback flow) |
| §3.4 `content` trigger key | Task A1 |
| §3.5 Phase 1 implementation scope | Tasks A–F |
| §4 Manual host1 setup | Task J1 |
| §5.2 deployment.yaml | Task H1 |
| §5.3 Volume mount detail | Task H1 (Caddyfile root = `/srv-root/current`) |
| §5.4 Caddyfile.j2 | Task H1 |
| §6 Deploy flow walkthrough | Phase K |
| §7 Validation plan | Task K2 |
| §8 Rollback & kill-switch | Task L2, README |
| §9 Gaps surfaced | Covered by §3 implementation (config.files primitive) |

**Known open questions** (surfaced in plan steps, must be resolved during execution):

1. Step I1.2: exact CP install path on host1 — check `ls /home/agent/` at execution time.
2. Step L2.4: `/api/components/{cid}/rollback` endpoint may not exist yet in the current code. The explore found `component_op` for start/stop/restart/healthcheck but not rollback. **Action during execution:** if missing, add a minimal `rollback` op that re-issues `request.rollback` to the daemon (scoped to this component) — see `docs/protocol.md §4` for the request shape. This is a follow-up task that may spill into a second commit. Alternative in Phase L2: re-run deploy with reverted YAML/content to achieve the same effect.

Both are handled as "check and possibly add" during execution — not placeholders in the plan.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-23-playmaestro-cloud-deploy.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Best fit for this plan: many small, independent tasks in three languages.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
