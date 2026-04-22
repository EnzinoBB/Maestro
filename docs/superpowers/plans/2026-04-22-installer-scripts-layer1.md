# Installer Scripts — Layer 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver Layer 1 of the installer design (2026-04-22): one-liner install for the Maestro control plane and daemons, backed by a GitHub Actions release pipeline that publishes versioned binaries (linux/darwin × amd64/arm64), a multi-arch Docker image for the CP, and self-serve install endpoints on the running CP.

**Architecture:** Multi-stage Dockerfile that cross-compiles all four daemon binaries and bundles them into the CP image; FastAPI endpoints serve the bundled binaries and a templated installer script; shell installers handle Docker bootstrap (CP) and systemd/launchd service installation with SHA256 verification (daemon); GitHub Actions workflows gate on tests for CI and produce versioned releases on tag push.

**Tech Stack:** Go 1.22 (daemon, cross-compiled), Python 3.12 + FastAPI (CP), Docker + BuildKit (image build), Bash (installers), GitHub Actions (CI/CD), shellcheck (lint), pytest + Go test (unit).

**Spec:** [`docs/superpowers/specs/2026-04-22-installer-scripts-design.md`](../specs/2026-04-22-installer-scripts-design.md)

---

## File Structure

**Created in this plan:**

| Path | Responsibility |
|---|---|
| `control-plane/docker-entrypoint.sh` | First-run token bootstrap (MySQL-style); ensures `MAESTRO_DAEMON_TOKEN` env is set before uvicorn starts. |
| `control-plane/app/api/install.py` | FastAPI router: `GET /install-daemon.sh` (templated), `GET /dist/*` (static mount). |
| `scripts/install-cp.sh` | New installer for the CP: pre-flight, compose file generation, `docker compose up`, health wait, logs hint. Lifecycle flags: `--version`, `--port`, `--data-dir`, `--upgrade`, `--uninstall`, `--purge`, `--no-docker-install`. |
| `.github/workflows/ci.yml` | Runs on push/PR: go test, pytest, ruff, go vet, shellcheck. |
| `.github/workflows/release.yml` | Runs on tag `v*`: build 4 binaries, build multi-arch Docker image, attest, release with SHA256SUMS + installer scripts. |
| `docs/release-checklist.md` | Maintainer checklist for cutting a release. |
| `daemon/internal/config/platform.go` | Go build-constrained files that enforce `systemd_enabled=false` on darwin. |
| `daemon/internal/config/platform_linux.go` | Linux variant (no-op). |
| `daemon/internal/config/platform_darwin.go` | Darwin variant (forces systemd off). |
| `daemon/internal/config/platform_test.go` | Tests for the platform gating. |

**Modified in this plan:**

| Path | Change |
|---|---|
| `control-plane/Dockerfile` | Replace with multi-stage: Go builder (cross-compiles 4 daemon binaries + SHA256SUMS) + Python runtime (bundles binaries under `/opt/maestro-cp/dist`, install script under `/opt/maestro-cp/scripts`, entrypoint wrapper). |
| `control-plane/app/main.py` | Mount the new `install` router; update CORS/static mount if needed. |
| `docker-compose.example.yml` | Update build context to repo root (needed for multi-stage build that reaches `daemon/`); update volume to `/data`; remove `CHANGE_ME` since token is auto-generated. |
| `Makefile` | Add `build-all` (cross-compiles 4 targets), `build-image`, `checksums` targets; update `build-linux` label to deprecate in favor of `build-all`. |
| `scripts/install-daemon.sh` | Full rewrite: cross-platform (Linux systemd + macOS launchd), auto-download from CP or GitHub, SHA256 verify, lifecycle flags `--upgrade`/`--uninstall`/`--purge`. Keeps `--token` flag (enrollment is Layer 2). |
| `README.md` | Rewrite "Quick start" around `install-cp.sh` / `install-daemon.sh`. Keep build instructions as "for contributors". |
| `docs/phase-1-completion.md` | Add paragraph noting Layer 1 packaging work delivered. |

---

## Task Sequence

The tasks are ordered so that each task leaves `main` buildable and tested. CI (Task 8) comes before release (Task 9) so we can validate test runs locally first. Docs come last (Task 10, 11) once the shapes are stable.

- **Phase A (Tasks 1–2):** Cross-platform daemon foundation.
- **Phase B (Tasks 3–5):** CP container improvements.
- **Phase C (Tasks 6–7):** Installer scripts.
- **Phase D (Tasks 8–9):** CI/release workflows.
- **Phase E (Tasks 10–11):** Documentation.

---

## Task 1: Darwin platform gating in daemon config

**Files:**
- Create: `daemon/internal/config/platform_linux.go`
- Create: `daemon/internal/config/platform_darwin.go`
- Create: `daemon/internal/config/platform_test.go`
- Modify: `daemon/internal/config/config.go:82-84`

**Why:** On macOS the daemon has no systemd; attempting to start systemd-managed services must not be possible. A build-constrained file forces `SystemdEnabled=false` at `Defaults()` time on darwin, so the Docker runner is the only available runner on Mac. Linux behavior is unchanged.

- [ ] **Step 1: Write the failing test**

Create `daemon/internal/config/platform_test.go`:

```go
package config

import (
	"runtime"
	"testing"
)

func TestPlatformGating_DisablesSystemdOnDarwin(t *testing.T) {
	c := &Config{SystemdEnabled: true}
	applyPlatformDefaults(c)
	if runtime.GOOS == "darwin" && c.SystemdEnabled {
		t.Fatal("expected SystemdEnabled=false on darwin, got true")
	}
	if runtime.GOOS == "linux" && !c.SystemdEnabled {
		t.Fatal("expected SystemdEnabled=true on linux, got false")
	}
}

func TestPlatformGating_LeavesDockerEnabledAlone(t *testing.T) {
	c := &Config{DockerEnabled: true, SystemdEnabled: true}
	applyPlatformDefaults(c)
	if !c.DockerEnabled {
		t.Fatal("expected DockerEnabled=true after platform gating, got false")
	}
}
```

- [ ] **Step 2: Run test, confirm it fails with "undefined: applyPlatformDefaults"**

Run: `cd daemon && go test ./internal/config/ -run TestPlatformGating -v`
Expected: build failure — `undefined: applyPlatformDefaults`.

- [ ] **Step 3: Create the Linux variant**

Create `daemon/internal/config/platform_linux.go`:

```go
//go:build linux

package config

// applyPlatformDefaults adjusts Config for the current OS. On Linux, no change.
func applyPlatformDefaults(_ *Config) {}
```

- [ ] **Step 4: Create the Darwin variant**

Create `daemon/internal/config/platform_darwin.go`:

```go
//go:build darwin

package config

// applyPlatformDefaults adjusts Config for the current OS. On Darwin, systemd
// is not available, so SystemdEnabled is always forced off regardless of
// config file contents or env vars.
func applyPlatformDefaults(c *Config) {
	c.SystemdEnabled = false
}
```

- [ ] **Step 5: Wire `applyPlatformDefaults` into `config.Load`**

Modify `daemon/internal/config/config.go` — inside `Load`, call `applyPlatformDefaults(c)` after env var overrides, before `c.Defaults()`:

Find:
```go
	if os.Getenv("MAESTROD_SYSTEMD") != "0" {
		c.SystemdEnabled = true
	}
	c.Defaults()
	return c, c.Validate()
```

Replace with:
```go
	if os.Getenv("MAESTROD_SYSTEMD") != "0" {
		c.SystemdEnabled = true
	}
	applyPlatformDefaults(c)
	c.Defaults()
	return c, c.Validate()
```

- [ ] **Step 6: Run test, confirm it passes**

Run: `cd daemon && go test ./internal/config/ -run TestPlatformGating -v`
Expected: PASS. Also run full config package: `cd daemon && go test ./internal/config/` — all pre-existing tests still pass.

- [ ] **Step 7: Cross-compile sanity check**

Run:
```
cd daemon
GOOS=darwin GOARCH=arm64 go build -o /tmp/maestrod-darwin-arm64 ./cmd/maestrod
GOOS=darwin GOARCH=amd64 go build -o /tmp/maestrod-darwin-amd64 ./cmd/maestrod
GOOS=linux  GOARCH=arm64 go build -o /tmp/maestrod-linux-arm64  ./cmd/maestrod
GOOS=linux  GOARCH=amd64 go build -o /tmp/maestrod-linux-amd64  ./cmd/maestrod
```
Expected: all four build successfully. Clean up with `rm /tmp/maestrod-*`.

- [ ] **Step 8: Commit**

```bash
git add daemon/internal/config/platform_linux.go daemon/internal/config/platform_darwin.go daemon/internal/config/platform_test.go daemon/internal/config/config.go
git commit -m "feat(daemon): add darwin platform gating, force systemd off on macOS"
```

---

## Task 2: Makefile cross-compile targets

**Files:**
- Modify: `Makefile:21-27`

**Why:** The current Makefile only builds `linux/amd64`. Layer 1 ships 4 binaries plus a SHA256SUMS. Add targets that the CI and local dev both use, so "build locally" matches "build in release workflow" byte-for-byte (modulo ldflags).

- [ ] **Step 1: Replace the build targets**

Modify `Makefile` — replace the `build-daemon` and `build-linux` sections, and add new targets. The `.PHONY` line also needs updating.

Find:
```makefile
.PHONY: help build build-daemon build-linux build-control-plane \
        test-unit test-integration test-e2e dev clean lint
```

Replace with:
```makefile
.PHONY: help build build-daemon build-all build-linux build-control-plane \
        checksums build-image test-unit test-integration test-e2e dev clean lint

VERSION ?= dev
LDFLAGS := -s -w -X main.Version=$(VERSION)
```

Find (the whole block):
```makefile
build-daemon:
	cd daemon && CGO_ENABLED=0 go build -o ../dist/maestrod ./cmd/maestrod

build-linux:
	cd daemon && CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -ldflags="-s -w" \
		-o ../dist/maestrod-linux-amd64 ./cmd/maestrod
```

Replace with:
```makefile
build-daemon:
	cd daemon && CGO_ENABLED=0 go build -ldflags="$(LDFLAGS)" \
		-o ../dist/maestrod ./cmd/maestrod

# Cross-compile all release targets. Matches the CI release matrix.
build-all:
	@mkdir -p dist
	cd daemon && CGO_ENABLED=0 GOOS=linux  GOARCH=amd64 go build -ldflags="$(LDFLAGS)" \
		-o ../dist/maestrod-linux-amd64 ./cmd/maestrod
	cd daemon && CGO_ENABLED=0 GOOS=linux  GOARCH=arm64 go build -ldflags="$(LDFLAGS)" \
		-o ../dist/maestrod-linux-arm64 ./cmd/maestrod
	cd daemon && CGO_ENABLED=0 GOOS=darwin GOARCH=amd64 go build -ldflags="$(LDFLAGS)" \
		-o ../dist/maestrod-darwin-amd64 ./cmd/maestrod
	cd daemon && CGO_ENABLED=0 GOOS=darwin GOARCH=arm64 go build -ldflags="$(LDFLAGS)" \
		-o ../dist/maestrod-darwin-arm64 ./cmd/maestrod

# Deprecated alias; kept for muscle memory of Phase 1.
build-linux: build-all

# Generate SHA256SUMS for all binaries in dist/.
checksums:
	cd dist && sha256sum maestrod-* > SHA256SUMS

# Build the CP multi-arch Docker image locally (single-arch: host arch).
# Used mostly for local verification; CI uses docker buildx for multi-arch.
build-image:
	docker build -f control-plane/Dockerfile \
		--build-arg VERSION=$(VERSION) \
		-t ghcr.io/enzinobb/maestro-cp:$(VERSION) .
```

Also update the `help` target block to list the new names:

Find:
```makefile
	@echo "  make build-daemon         - native go build of maestrod (dist/maestrod)"
	@echo "  make build-linux          - cross-compile maestrod for linux/amd64"
```

Replace with:
```makefile
	@echo "  make build-daemon         - native go build of maestrod (dist/maestrod)"
	@echo "  make build-all            - cross-compile maestrod for linux+darwin × amd64+arm64"
	@echo "  make checksums            - write dist/SHA256SUMS"
	@echo "  make build-image          - build local CP Docker image"
```

- [ ] **Step 2: Verify cross-compilation works**

Run: `make build-all && ls dist/`
Expected: 4 binaries: `maestrod-linux-amd64`, `maestrod-linux-arm64`, `maestrod-darwin-amd64`, `maestrod-darwin-arm64`.

- [ ] **Step 3: Verify checksums work**

Run: `make checksums && cat dist/SHA256SUMS`
Expected: 4 lines, one per binary, each with a 64-hex checksum followed by the file name.

- [ ] **Step 4: Verify SHA256SUMS is usable**

Run: `cd dist && sha256sum -c SHA256SUMS`
Expected: four `OK` lines. If any line is not `OK`, stop and investigate — the `sha256sum` output format must match the CI expectation.

- [ ] **Step 5: Commit**

```bash
git add Makefile
git commit -m "build: add cross-platform build-all and checksums targets"
```

---

## Task 3: Docker entrypoint with MySQL-style token bootstrap

**Files:**
- Create: `control-plane/docker-entrypoint.sh`

**Why:** The CP container today expects `MAESTRO_DAEMON_TOKEN` in env. Layer 1 spec §4.2: if the admin sets the env var, use it; else if a token has been persisted to `/data/daemon-token`, reuse it; else generate a new one on first boot and print it prominently. Persistence on the `/data` volume ensures restarts preserve auth.

- [ ] **Step 1: Create the entrypoint**

Create `control-plane/docker-entrypoint.sh`:

```bash
#!/bin/sh
# docker-entrypoint.sh — bootstrap MAESTRO_DAEMON_TOKEN on first start.
# Precedence:
#   1. MAESTRO_DAEMON_TOKEN env var set by the admin  → use as-is.
#   2. /data/daemon-token file exists                → read it.
#   3. Generate random 32-byte hex, persist, print banner.
set -eu

TOKEN_FILE="${MAESTRO_TOKEN_FILE:-/data/daemon-token}"

if [ -n "${MAESTRO_DAEMON_TOKEN:-}" ]; then
    : # admin-provided token, nothing to do
elif [ -s "$TOKEN_FILE" ]; then
    MAESTRO_DAEMON_TOKEN="$(cat "$TOKEN_FILE")"
    export MAESTRO_DAEMON_TOKEN
else
    mkdir -p "$(dirname "$TOKEN_FILE")"
    MAESTRO_DAEMON_TOKEN="$(python -c 'import secrets; print(secrets.token_hex(32))')"
    umask 077
    printf '%s' "$MAESTRO_DAEMON_TOKEN" > "$TOKEN_FILE"
    export MAESTRO_DAEMON_TOKEN
    cat <<EOF
===========================================================
  GENERATED MAESTRO DAEMON TOKEN (save this, shown once):
    $MAESTRO_DAEMON_TOKEN
  Also stored at $TOKEN_FILE inside the container.
===========================================================
EOF
fi

exec "$@"
```

- [ ] **Step 2: Make it executable**

Run: `chmod +x control-plane/docker-entrypoint.sh`

- [ ] **Step 3: Verify with shellcheck**

Run: `shellcheck control-plane/docker-entrypoint.sh`
Expected: no output (clean). If shellcheck is not installed locally: `docker run --rm -v "$PWD":/mnt koalaman/shellcheck:stable control-plane/docker-entrypoint.sh`.

- [ ] **Step 4: Smoke-test the three branches locally**

Run each of these in sequence — each should print the expected behavior and exit 0.

```bash
# Branch 1: env var set → no banner, no file write
TMPDIR=$(mktemp -d)
MAESTRO_DAEMON_TOKEN=preset MAESTRO_TOKEN_FILE="$TMPDIR/t" \
  sh control-plane/docker-entrypoint.sh sh -c 'echo "token=$MAESTRO_DAEMON_TOKEN"'
# Expected stdout: "token=preset"; no banner; no file at $TMPDIR/t
test ! -f "$TMPDIR/t" || echo "FAIL: file should not exist"

# Branch 2: file present → reuse, no banner
echo -n "persisted" > "$TMPDIR/t"
MAESTRO_TOKEN_FILE="$TMPDIR/t" \
  sh control-plane/docker-entrypoint.sh sh -c 'echo "token=$MAESTRO_DAEMON_TOKEN"'
# Expected: "token=persisted"; no banner

# Branch 3: first run → generate, write, banner
rm -f "$TMPDIR/t"
MAESTRO_TOKEN_FILE="$TMPDIR/t" \
  sh control-plane/docker-entrypoint.sh sh -c 'echo "token=$MAESTRO_DAEMON_TOKEN"'
# Expected: banner printed to stdout, "token=<64-hex>", $TMPDIR/t written

rm -rf "$TMPDIR"
```

- [ ] **Step 5: Commit**

```bash
git add control-plane/docker-entrypoint.sh
git commit -m "feat(cp): add docker entrypoint for MySQL-style token bootstrap"
```

---

## Task 4: CP install/download endpoints

**Files:**
- Create: `control-plane/app/api/install.py`
- Modify: `control-plane/app/main.py:13-18,42-46`
- Create: `control-plane/tests/unit/test_install_endpoints.py`

**Why:** Spec §4.3. The running CP must serve the bundled daemon binaries and a templated `install-daemon.sh` with its own URL baked in, so `curl https://playmaestro.cloud/install-daemon.sh | sudo bash` works out of the box.

- [ ] **Step 1: Write failing tests**

Create `control-plane/tests/unit/test_install_endpoints.py`:

```python
"""Tests for /install-daemon.sh and /dist/* endpoints (Layer 1)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def dist_fixture(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "maestrod-linux-amd64").write_bytes(b"FAKE_BINARY_AMD64")
    (dist / "maestrod-linux-arm64").write_bytes(b"FAKE_BINARY_ARM64")
    (dist / "SHA256SUMS").write_text(
        "aaa  maestrod-linux-amd64\nbbb  maestrod-linux-arm64\n"
    )

    script = tmp_path / "install-daemon.sh"
    script.write_text("#!/usr/bin/env bash\nDEFAULT_CP_URL=\"\"\necho hi\n")

    monkeypatch.setenv("MAESTRO_DIST_DIR", str(dist))
    monkeypatch.setenv("MAESTRO_INSTALL_SCRIPT", str(script))
    return dist, script


def _app(_fixture):
    # Re-import so env vars are picked up in the router factory
    from control_plane.app.main import create_app  # noqa: E402
    return create_app()


def test_dist_serves_binary(dist_fixture):
    client = TestClient(_app(dist_fixture))
    r = client.get("/dist/maestrod-linux-amd64")
    assert r.status_code == 200
    assert r.content == b"FAKE_BINARY_AMD64"


def test_dist_serves_checksums(dist_fixture):
    client = TestClient(_app(dist_fixture))
    r = client.get("/dist/SHA256SUMS")
    assert r.status_code == 200
    assert b"maestrod-linux-amd64" in r.content


def test_install_script_substitutes_cp_url(dist_fixture):
    client = TestClient(_app(dist_fixture))
    r = client.get(
        "/install-daemon.sh",
        headers={"host": "playmaestro.cloud"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/x-shellscript")
    body = r.text
    # The placeholder must have been substituted with a value that includes our host.
    assert "DEFAULT_CP_URL=\"\"" not in body
    assert "playmaestro.cloud" in body
```

Note: the import path `control_plane.app.main` assumes the tests are run with `PYTHONPATH=control-plane` or equivalent. If the existing test suite uses `control-plane/tests/` with a different import path, match that convention — inspect `control-plane/tests/unit/test_api.py` to see how it imports.

- [ ] **Step 2: Run test, confirm it fails**

Run: `cd control-plane && python -m pytest tests/unit/test_install_endpoints.py -v`
Expected: ImportError or 404 — the router doesn't exist yet.

- [ ] **Step 3: Create the router**

Create `control-plane/app/api/install.py`:

```python
"""Endpoints that serve the daemon binary bundle and a templated installer.

These are part of Layer 1 of the installer design (2026-04-22). They let a
running control plane act as a self-serve install source for new daemons.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse


router = APIRouter()


def _dist_dir() -> Path:
    return Path(os.environ.get("MAESTRO_DIST_DIR", "/opt/maestro-cp/dist"))


def _install_script() -> Path:
    return Path(
        os.environ.get(
            "MAESTRO_INSTALL_SCRIPT",
            "/opt/maestro-cp/scripts/install-daemon.sh",
        )
    )


# Files we are willing to serve from the dist dir. Keep this whitelist
# restrictive to avoid path-traversal surprises.
_DIST_ALLOWED = {
    "maestrod-linux-amd64",
    "maestrod-linux-arm64",
    "maestrod-darwin-amd64",
    "maestrod-darwin-arm64",
    "SHA256SUMS",
}


@router.get("/dist/{name}")
def serve_dist(name: str):
    if name not in _DIST_ALLOWED:
        raise HTTPException(status_code=404)
    path = _dist_dir() / name
    if not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(
        path=str(path),
        media_type="application/octet-stream",
        filename=name,
    )


@router.get("/install-daemon.sh")
def serve_install_script(request: Request) -> Response:
    path = _install_script()
    if not path.is_file():
        raise HTTPException(status_code=404)
    body = path.read_text(encoding="utf-8")
    # Substitute the placeholder DEFAULT_CP_URL="" with the URL of this CP.
    cp_url = f"{request.url.scheme}://{request.headers.get('host', request.url.netloc)}"
    body = body.replace('DEFAULT_CP_URL=""', f'DEFAULT_CP_URL="{cp_url}"')
    return Response(
        content=body,
        media_type="text/x-shellscript; charset=utf-8",
    )
```

- [ ] **Step 4: Wire the router into `main.py`**

Modify `control-plane/app/main.py`. Find:

```python
from .api.router import router as api_router
from .api.ui import router as ui_router
```

Add below:

```python
from .api.install import router as install_router
```

Find:

```python
    app.include_router(api_router)
    app.include_router(ui_router)
```

Add below:

```python
    app.include_router(install_router)
```

- [ ] **Step 5: Run tests, confirm they pass**

Run: `cd control-plane && python -m pytest tests/unit/test_install_endpoints.py -v`
Expected: all three tests PASS.

- [ ] **Step 6: Run the full unit suite as a regression check**

Run: `cd control-plane && python -m pytest tests/unit -q`
Expected: all tests pass (no pre-existing tests broken by the router addition).

- [ ] **Step 7: Commit**

```bash
git add control-plane/app/api/install.py control-plane/app/main.py control-plane/tests/unit/test_install_endpoints.py
git commit -m "feat(cp): add /install-daemon.sh and /dist/* endpoints"
```

---

## Task 5: Dockerfile multi-stage build + compose example update

**Files:**
- Modify: `control-plane/Dockerfile` (full rewrite)
- Modify: `docker-compose.example.yml`

**Why:** The CP image must ship all 4 daemon binaries + SHA256SUMS + the installer script, and use the new entrypoint. The simplest reproducible approach is a multi-stage build: a Go builder stage cross-compiles all four binaries in the same image build, then a Python runtime stage copies them in. This guarantees the binaries served by `/dist/*` match the CP version.

- [ ] **Step 1: Rewrite the Dockerfile**

Overwrite `control-plane/Dockerfile` with:

```dockerfile
# syntax=docker/dockerfile:1.6
# ---- Stage 1: cross-compile daemon binaries ----
FROM golang:1.22-alpine AS daemon-builder
ARG VERSION=dev
WORKDIR /src
COPY daemon/go.mod daemon/go.sum ./
RUN go mod download
COPY daemon/ ./
RUN set -eu; \
    mkdir -p /out; \
    for os in linux darwin; do \
      for arch in amd64 arm64; do \
        CGO_ENABLED=0 GOOS=$os GOARCH=$arch \
          go build -trimpath -ldflags="-s -w -X main.Version=${VERSION}" \
          -o /out/maestrod-${os}-${arch} ./cmd/maestrod; \
      done; \
    done; \
    cd /out && sha256sum maestrod-* > SHA256SUMS

# ---- Stage 2: CP runtime ----
FROM python:3.12-slim

WORKDIR /app
COPY control-plane/pyproject.toml ./
RUN pip install --no-cache-dir fastapi 'uvicorn[standard]' pydantic pyyaml jinja2 \
    sqlalchemy aiosqlite websockets httpx click mcp python-multipart

COPY control-plane/app/ ./app/
COPY control-plane/web/ ./web/
COPY control-plane/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY scripts/install-daemon.sh /opt/maestro-cp/scripts/install-daemon.sh
COPY --from=daemon-builder /out/ /opt/maestro-cp/dist/

RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
             /opt/maestro-cp/scripts/install-daemon.sh

EXPOSE 8000
ENV PYTHONUNBUFFERED=1 \
    MAESTRO_DIST_DIR=/opt/maestro-cp/dist \
    MAESTRO_INSTALL_SCRIPT=/opt/maestro-cp/scripts/install-daemon.sh

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Note:** The `daemon/` and `scripts/` directories are now referenced from the build context. The build context must therefore be the **repo root**, not `control-plane/`. This requires updating `docker-compose.example.yml` in the next step.

- [ ] **Step 2: Update docker-compose.example.yml**

Overwrite `docker-compose.example.yml`:

```yaml
services:
  control-plane:
    build:
      context: .
      dockerfile: control-plane/Dockerfile
      args:
        VERSION: dev
    # Or pin to a published image:
    # image: ghcr.io/enzinobb/maestro-cp:latest
    ports:
      - "8000:8000"
    environment:
      MAESTRO_DB: /data/cp.db
      MAESTRO_LOG_LEVEL: INFO
      # Leave MAESTRO_DAEMON_TOKEN unset on first start — the container will
      # auto-generate one, persist it to /data/daemon-token, and print it
      # prominently in the logs. To use your own token, set it here.
      # MAESTRO_DAEMON_TOKEN: ""
    volumes:
      - cp-data:/data
volumes:
  cp-data:
```

- [ ] **Step 3: Build the image locally and verify**

Run (from repo root):
```
docker build -f control-plane/Dockerfile --build-arg VERSION=dev-test -t maestro-cp:test .
```
Expected: build completes. First build may take 2–4 minutes (Go module download + cross-compile × 4).

- [ ] **Step 4: Verify bundled artifacts**

Run:
```
docker run --rm maestro-cp:test ls /opt/maestro-cp/dist/
```
Expected output: `SHA256SUMS  maestrod-darwin-amd64  maestrod-darwin-arm64  maestrod-linux-amd64  maestrod-linux-arm64`

- [ ] **Step 5: Verify the token bootstrap branch with a real container**

```
CONTAINER=$(docker run -d --rm -p 18000:8000 -v /tmp/mcp-test-data:/data maestro-cp:test)
sleep 3
docker logs "$CONTAINER" | grep -A1 "GENERATED MAESTRO DAEMON TOKEN"
curl -fsS http://localhost:18000/healthz
curl -fsSI http://localhost:18000/dist/SHA256SUMS | head -1
curl -fsS http://localhost:18000/install-daemon.sh | head -5
docker stop "$CONTAINER"
rm -rf /tmp/mcp-test-data
```
Expected: banner with a 64-hex token; healthz returns `{"ok":true}`; dist/SHA256SUMS returns 200; install-daemon.sh returns the script (content at this stage may still be the old Phase 1 script — will be replaced in Task 7).

- [ ] **Step 6: Verify token persistence across restarts**

```
docker run -d --name mcp-persist -p 18001:8000 -v /tmp/mcp-persist-data:/data maestro-cp:test
sleep 3
FIRST=$(docker logs mcp-persist 2>&1 | grep -A1 "GENERATED" | tail -1 | tr -d ' ')
docker restart mcp-persist
sleep 3
SECOND_LOGS=$(docker logs mcp-persist 2>&1 | tail -20)
echo "$SECOND_LOGS" | grep -q "GENERATED" && echo "FAIL: token regenerated on restart" || echo "OK: no regeneration"
docker rm -f mcp-persist
rm -rf /tmp/mcp-persist-data
```
Expected: no banner on restart.

- [ ] **Step 7: Commit**

```bash
git add control-plane/Dockerfile docker-compose.example.yml
git commit -m "build(cp): multi-stage Dockerfile with bundled daemon binaries"
```

---

## Task 6: scripts/install-cp.sh

**Files:**
- Create: `scripts/install-cp.sh`

**Why:** Spec §4.1. A fresh VM should become a running CP with one command: `curl … | sudo bash`. The script bootstraps Docker if missing, generates a compose file in `/opt/maestro-cp/`, starts the service, waits for healthz, and tells the admin how to retrieve the auto-generated token.

- [ ] **Step 1: Create the script**

Create `scripts/install-cp.sh`:

```bash
#!/usr/bin/env bash
# install-cp.sh — install the Maestro control plane via Docker Compose.
#
# Usage:
#   curl -fsSL https://github.com/EnzinoBB/Maestro/releases/latest/download/install-cp.sh | sudo bash
#   curl -fsSL …/install-cp.sh | sudo bash -s -- --port 9000 --version v0.2.0
#
# Flags:
#   --version <tag>     Image version to pin (default: latest)
#   --port <N>          Host port (default: 8000)
#   --data-dir <path>   Named volume source path (default: docker-managed)
#   --no-docker-install Fail instead of auto-installing Docker
#   --upgrade           Pull new image, restart, preserve volume
#   --uninstall         Stop + remove container; keep volume
#   --purge             With --uninstall: also remove volume and install dir
set -euo pipefail

VERSION="latest"
PORT="8000"
DATA_DIR=""
NO_DOCKER_INSTALL=""
MODE="install"
PURGE=""

INSTALL_DIR="/opt/maestro-cp"
IMAGE="ghcr.io/enzinobb/maestro-cp"

usage() {
  sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --version)           VERSION="$2"; shift 2;;
    --port)              PORT="$2"; shift 2;;
    --data-dir)          DATA_DIR="$2"; shift 2;;
    --no-docker-install) NO_DOCKER_INSTALL="1"; shift;;
    --upgrade)           MODE="upgrade"; shift;;
    --uninstall)         MODE="uninstall"; shift;;
    --purge)             PURGE="1"; shift;;
    -h|--help)           usage 0;;
    *) echo "unknown argument: $1" >&2; usage 2;;
  esac
done

require_root() {
  if [[ $EUID -ne 0 ]]; then
    echo "This installer must run as root (prefix with sudo)." >&2
    exit 1
  fi
}

ensure_docker() {
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    return 0
  fi
  if [[ -n "$NO_DOCKER_INSTALL" ]]; then
    echo "Docker or 'docker compose' v2 is missing and --no-docker-install is set." >&2
    exit 3
  fi
  echo "Installing Docker via get.docker.com …"
  curl -fsSL https://get.docker.com | sh
  if ! docker compose version >/dev/null 2>&1; then
    echo "Docker installed but 'docker compose' v2 is not available. Install it manually." >&2
    exit 3
  fi
}

render_compose() {
  mkdir -p "$INSTALL_DIR"
  local vol_spec="cp-data:/data"
  local vol_def="volumes:\n  cp-data:"
  if [[ -n "$DATA_DIR" ]]; then
    mkdir -p "$DATA_DIR"
    vol_spec="${DATA_DIR}:/data"
    vol_def=""
  fi
  cat > "$INSTALL_DIR/docker-compose.yml" <<EOF
services:
  control-plane:
    image: ${IMAGE}:${VERSION}
    restart: unless-stopped
    ports:
      - "${PORT}:8000"
    environment:
      MAESTRO_DB: /data/cp.db
      MAESTRO_LOG_LEVEL: INFO
    volumes:
      - ${vol_spec}
$( [[ -n "$vol_def" ]] && printf "%b\n" "$vol_def" )
EOF
}

wait_healthy() {
  local tries=30
  while (( tries > 0 )); do
    if curl -fsS "http://localhost:${PORT}/healthz" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2; tries=$((tries-1))
  done
  echo "CP did not become healthy within 60s. Last logs:" >&2
  (cd "$INSTALL_DIR" && docker compose logs --tail 50) >&2 || true
  return 4
}

do_install() {
  require_root
  ensure_docker
  render_compose
  (cd "$INSTALL_DIR" && docker compose pull && docker compose up -d)
  wait_healthy
  cat <<EOF

Maestro Control Plane is running.
  UI:          http://<this-host>:${PORT}
  Health:      http://<this-host>:${PORT}/healthz
  Compose:     $INSTALL_DIR/docker-compose.yml

To retrieve the auto-generated daemon token:
  docker compose -f $INSTALL_DIR/docker-compose.yml logs control-plane | grep -A1 "GENERATED MAESTRO DAEMON TOKEN"

EOF
}

do_upgrade() {
  require_root
  if [[ ! -f "$INSTALL_DIR/docker-compose.yml" ]]; then
    echo "$INSTALL_DIR/docker-compose.yml not found; run install first." >&2
    exit 5
  fi
  # Rewrite compose with possibly new --version or --port before pulling.
  render_compose
  (cd "$INSTALL_DIR" && docker compose pull && docker compose up -d)
  wait_healthy
  echo "Upgrade complete."
}

do_uninstall() {
  require_root
  if [[ -f "$INSTALL_DIR/docker-compose.yml" ]]; then
    if [[ -n "$PURGE" ]]; then
      (cd "$INSTALL_DIR" && docker compose down -v)
      rm -rf "$INSTALL_DIR"
      echo "Purged: containers, volumes, $INSTALL_DIR."
    else
      (cd "$INSTALL_DIR" && docker compose down)
      echo "Stopped. Volume and $INSTALL_DIR preserved. Use --uninstall --purge to wipe."
    fi
  else
    echo "Nothing to uninstall ($INSTALL_DIR missing)."
  fi
}

case "$MODE" in
  install)   do_install;;
  upgrade)   do_upgrade;;
  uninstall) do_uninstall;;
esac
```

- [ ] **Step 2: Make executable**

Run: `chmod +x scripts/install-cp.sh`

- [ ] **Step 3: Lint with shellcheck**

Run: `shellcheck scripts/install-cp.sh`
Expected: clean (no warnings). If a warning fires, fix it before continuing — installer scripts must be shellcheck-clean.

- [ ] **Step 4: Dry-run syntax check**

Run: `bash -n scripts/install-cp.sh`
Expected: no output (syntactically valid).

- [ ] **Step 5: Test `--help`**

Run: `scripts/install-cp.sh --help`
Expected: usage block printed, exit 0.

- [ ] **Step 6: End-to-end test against a local image**

Requires the image built in Task 5 (`maestro-cp:test`). Tag it as `ghcr.io/enzinobb/maestro-cp:local-test` and run the installer with a pinned version, using sudo:

```
docker tag maestro-cp:test ghcr.io/enzinobb/maestro-cp:local-test
sudo scripts/install-cp.sh --version local-test --port 18080
sudo scripts/install-cp.sh --uninstall --purge
```

**Note:** if you're developing on Windows/WSL without easy sudo, defer this step to a Linux VM or CI. But the shellcheck + dry-run pass is mandatory before commit.

- [ ] **Step 7: Commit**

```bash
git add scripts/install-cp.sh
git commit -m "feat(install): add install-cp.sh for one-liner CP deploy"
```

---

## Task 7: Rewrite scripts/install-daemon.sh for auto-download + cross-platform

**Files:**
- Modify: `scripts/install-daemon.sh` (full rewrite)

**Why:** The existing script requires `scp`-ing the binary manually and only supports Linux systemd. Layer 1 rewrites it to:

1. Auto-download the binary from the CP (`${CP_URL}/dist/maestrod-<os>-<arch>`) or GitHub as fallback.
2. Verify SHA256 against `${CP_URL}/dist/SHA256SUMS`.
3. Install a systemd unit (Linux) or a launchd plist (macOS).
4. Support `--upgrade` and `--uninstall [--purge]`.
5. Keep the existing `--token` flag (enrollment replaces this in Layer 2 / Phase 3, not now).

- [ ] **Step 1: Overwrite the script**

Overwrite `scripts/install-daemon.sh`:

```bash
#!/usr/bin/env bash
# install-daemon.sh — install, upgrade, or uninstall the Maestro daemon.
#
# Typical install (binary + service):
#   curl -fsSL https://playmaestro.cloud/install-daemon.sh | sudo bash -s -- \
#     --host-id api-01 --token <TOKEN>
#
# Or via GitHub:
#   curl -fsSL https://github.com/EnzinoBB/Maestro/releases/latest/download/install-daemon.sh | \
#     sudo bash -s -- --cp-url https://cp.example --host-id api-01 --token <TOKEN>
#
# Flags:
#   --cp-url <url>       Control plane URL (also determines binary source).
#                        If omitted, uses DEFAULT_CP_URL baked into the script.
#   --host-id <id>       Identifier for this host (default: `hostname -s`)
#   --token <token>      Shared daemon token (required for install)
#   --version <tag>      Pin binary version; default: fetch from CP, fallback to GitHub latest
#   --from-github        Force GitHub as binary source
#   --insecure           Accept self-signed TLS / http CP (sets daemon insecure flag)
#   --upgrade            Download new binary, restart service
#   --uninstall          Stop + remove service and binary
#   --purge              With --uninstall: also remove config and state dir
set -euo pipefail

# DEFAULT_CP_URL is string-substituted by the CP's /install-daemon.sh endpoint.
# Leave empty in the repo copy; CI ensures this line survives unchanged.
DEFAULT_CP_URL=""

GITHUB_LATEST="https://github.com/EnzinoBB/Maestro/releases/latest/download"
GITHUB_RELEASE_FMT="https://github.com/EnzinoBB/Maestro/releases/download/%s"

CP_URL=""
HOST_ID=""
TOKEN=""
VERSION=""
FROM_GITHUB=""
INSECURE=""
MODE="install"
PURGE=""

usage() {
  sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --cp-url)      CP_URL="$2"; shift 2;;
    --host-id)     HOST_ID="$2"; shift 2;;
    --token)       TOKEN="$2"; shift 2;;
    --version)     VERSION="$2"; shift 2;;
    --from-github) FROM_GITHUB="1"; shift;;
    --insecure)    INSECURE="1"; shift;;
    --upgrade)     MODE="upgrade"; shift;;
    --uninstall)   MODE="uninstall"; shift;;
    --purge)       PURGE="1"; shift;;
    -h|--help)     usage 0;;
    *) echo "unknown argument: $1" >&2; usage 2;;
  esac
done

[[ -z "$CP_URL" ]] && CP_URL="$DEFAULT_CP_URL"

# ---- Platform detection ------------------------------------------------------
OS_NAME="$(uname -s)"
ARCH_NAME="$(uname -m)"
case "$ARCH_NAME" in
  x86_64|amd64) ARCH="amd64";;
  aarch64|arm64) ARCH="arm64";;
  *) echo "unsupported arch: $ARCH_NAME" >&2; exit 2;;
esac
case "$OS_NAME" in
  Linux)  OS="linux";  SERVICE_KIND="systemd";;
  Darwin) OS="darwin"; SERVICE_KIND="launchd";;
  *) echo "unsupported OS: $OS_NAME" >&2; exit 2;;
esac

# ---- Paths -------------------------------------------------------------------
if [[ "$OS" == "linux" ]]; then
  BIN_DST="/usr/local/bin/maestrod"
  CFG_DIR="/etc/maestrod"
  WORK_DIR="/var/lib/maestrod"
  UNIT_FILE="/etc/systemd/system/maestro-daemon.service"
else
  BIN_DST="/usr/local/bin/maestrod"
  CFG_DIR="/usr/local/etc/maestrod"
  WORK_DIR="/usr/local/var/maestrod"
  PLIST_FILE="/Library/LaunchDaemons/com.maestro.daemon.plist"
fi
CFG_FILE="$CFG_DIR/config.yaml"

require_root() {
  if [[ $EUID -ne 0 ]]; then
    echo "This installer must run as root (prefix with sudo)." >&2
    exit 1
  fi
}

# ---- Download binary + verify checksum --------------------------------------
download_binary() {
  local tmpdir; tmpdir="$(mktemp -d)"
  trap 'rm -rf "$tmpdir"' RETURN
  local binary_name="maestrod-${OS}-${ARCH}"
  local base_url checksum_url

  if [[ -n "$FROM_GITHUB" || -z "$CP_URL" ]]; then
    if [[ -n "$VERSION" ]]; then
      # shellcheck disable=SC2059
      base_url="$(printf "$GITHUB_RELEASE_FMT" "$VERSION")"
    else
      base_url="$GITHUB_LATEST"
    fi
  else
    base_url="${CP_URL%/}/dist"
  fi
  checksum_url="${base_url}/SHA256SUMS"

  echo "Downloading $binary_name from $base_url …"
  curl -fsSL "${base_url}/${binary_name}" -o "$tmpdir/$binary_name"
  curl -fsSL "$checksum_url" -o "$tmpdir/SHA256SUMS"

  echo "Verifying SHA256 …"
  (cd "$tmpdir" && grep " $binary_name\$" SHA256SUMS | sha256sum -c -) || {
    echo "Checksum mismatch for $binary_name — aborting" >&2
    exit 6
  }

  install -m 0755 "$tmpdir/$binary_name" "$BIN_DST"
}

# ---- Write config -----------------------------------------------------------
write_config() {
  mkdir -p "$CFG_DIR" "$WORK_DIR"
  chmod 0750 "$CFG_DIR"
  local systemd_flag="true"
  [[ "$OS" == "darwin" ]] && systemd_flag="false"
  cat > "$CFG_FILE" <<EOF
host_id: ${HOST_ID}
endpoint: ${CP_URL%/}/ws/daemon
token: ${TOKEN}
working_dir: ${WORK_DIR}
state_path: ${WORK_DIR}/state.db
docker_enabled: true
systemd_enabled: ${systemd_flag}
insecure: ${INSECURE:-false}
metrics_interval_sec: 30
EOF
  chmod 0640 "$CFG_FILE"
}

# ---- Service install (systemd) ----------------------------------------------
install_systemd() {
  cat > "$UNIT_FILE" <<EOF
[Unit]
Description=Maestro daemon (maestrod)
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
ExecStart=${BIN_DST} --config ${CFG_FILE}
Restart=always
RestartSec=5
User=root
Group=root
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now maestro-daemon.service
}

# ---- Service install (launchd) ----------------------------------------------
install_launchd() {
  cat > "$PLIST_FILE" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.maestro.daemon</string>
  <key>ProgramArguments</key>
    <array>
      <string>${BIN_DST}</string>
      <string>--config</string>
      <string>${CFG_FILE}</string>
    </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/var/log/maestro-daemon.out.log</string>
  <key>StandardErrorPath</key><string>/var/log/maestro-daemon.err.log</string>
</dict>
</plist>
EOF
  chmod 0644 "$PLIST_FILE"
  launchctl unload "$PLIST_FILE" 2>/dev/null || true
  launchctl load "$PLIST_FILE"
}

# ---- Service control (both) -------------------------------------------------
service_start() {
  if [[ "$SERVICE_KIND" == "systemd" ]]; then install_systemd
  else install_launchd; fi
}

service_stop() {
  if [[ "$SERVICE_KIND" == "systemd" ]]; then
    systemctl disable --now maestro-daemon.service 2>/dev/null || true
    rm -f "$UNIT_FILE"
    systemctl daemon-reload
  else
    launchctl unload "$PLIST_FILE" 2>/dev/null || true
    rm -f "$PLIST_FILE"
  fi
}

service_status_ok() {
  if [[ "$SERVICE_KIND" == "systemd" ]]; then
    systemctl is-active --quiet maestro-daemon.service
  else
    launchctl list | grep -q com.maestro.daemon
  fi
}

wait_running() {
  local tries=10
  while (( tries > 0 )); do
    if service_status_ok; then return 0; fi
    sleep 1; tries=$((tries-1))
  done
  echo "daemon did not start within 10s; recent logs:" >&2
  if [[ "$SERVICE_KIND" == "systemd" ]]; then
    journalctl -u maestro-daemon.service -n 30 --no-pager >&2 || true
  else
    tail -n 30 /var/log/maestro-daemon.err.log 2>/dev/null >&2 || true
  fi
  return 7
}

# ---- Modes ------------------------------------------------------------------
do_install() {
  require_root
  [[ -z "$HOST_ID" ]] && HOST_ID="$(hostname -s)"
  if [[ -z "$TOKEN" ]]; then
    echo "--token is required (read the CP logs: GENERATED MAESTRO DAEMON TOKEN)" >&2
    exit 2
  fi
  if [[ -z "$CP_URL" ]]; then
    echo "--cp-url is required (or invoke via an enroll URL served by the CP)" >&2
    exit 2
  fi
  download_binary
  write_config
  service_start
  wait_running
  echo "maestrod installed and running (host_id=$HOST_ID, endpoint=$CP_URL)."
}

do_upgrade() {
  require_root
  if [[ ! -f "$CFG_FILE" ]]; then
    echo "$CFG_FILE not found; run install first." >&2
    exit 5
  fi
  # Derive CP_URL from existing config if not overridden.
  if [[ -z "$CP_URL" ]]; then
    CP_URL="$(awk -F': *' '/^endpoint:/ {print $2; exit}' "$CFG_FILE" | sed 's#/ws/daemon$##')"
  fi
  if [[ "$SERVICE_KIND" == "systemd" ]]; then
    systemctl stop maestro-daemon.service
  else
    launchctl unload "$PLIST_FILE" 2>/dev/null || true
  fi
  download_binary
  service_start
  wait_running
  echo "maestrod upgraded."
}

do_uninstall() {
  require_root
  service_stop
  rm -f "$BIN_DST"
  if [[ -n "$PURGE" ]]; then
    rm -rf "$CFG_DIR" "$WORK_DIR"
    echo "Purged: binary, service unit, config, state."
  else
    echo "Removed binary and service. Config and state preserved. Use --purge to wipe."
  fi
}

case "$MODE" in
  install)   do_install;;
  upgrade)   do_upgrade;;
  uninstall) do_uninstall;;
esac
```

- [ ] **Step 2: Make executable and lint**

Run:
```
chmod +x scripts/install-daemon.sh
shellcheck scripts/install-daemon.sh
bash -n scripts/install-daemon.sh
```
Expected: `shellcheck` clean, `bash -n` no output.

- [ ] **Step 3: Verify the DEFAULT_CP_URL placeholder still matches what the CP endpoint substitutes**

The CP's `/install-daemon.sh` endpoint (Task 4) replaces `DEFAULT_CP_URL=""` with `DEFAULT_CP_URL="<cp-url>"`. Confirm the exact string is still present in the script:

Run: `grep -c 'DEFAULT_CP_URL=""' scripts/install-daemon.sh`
Expected: `1` (exactly one match — the replacement target).

- [ ] **Step 4: Test --help and --uninstall against a clean system**

Run: `scripts/install-daemon.sh --help`
Expected: usage block.

End-to-end testing of the install flow requires a Linux VM with systemd and a running CP — defer to the CI smoke test in Task 8, or do it manually on `server2` from the `maestro-target-machines` memory.

- [ ] **Step 5: Commit**

```bash
git add scripts/install-daemon.sh
git commit -m "feat(install): rewrite install-daemon.sh with auto-download, checksum, cross-platform, upgrade/uninstall"
```

---

## Task 8: CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

**Why:** Every push/PR to `main` must run the unit tests and lints before anything can be released. Also run shellcheck on every script so the installers stay clean.

- [ ] **Step 1: Create the workflow**

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

jobs:
  test-go:
    name: Go test + vet
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with:
          go-version: '1.22'
          cache-dependency-path: daemon/go.sum
      - name: go vet
        working-directory: daemon
        run: go vet ./...
      - name: go test
        working-directory: daemon
        run: go test ./... -count=1

  test-python:
    name: Python test + ruff
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install dependencies
        working-directory: control-plane
        run: |
          python -m pip install --upgrade pip
          pip install fastapi 'uvicorn[standard]' pydantic pyyaml jinja2 \
              sqlalchemy aiosqlite websockets httpx click mcp python-multipart \
              pytest pytest-asyncio ruff
      - name: ruff
        working-directory: control-plane
        run: ruff check app/
      - name: pytest unit
        working-directory: control-plane
        run: python -m pytest tests/unit -q

  shellcheck:
    name: shellcheck
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run shellcheck
        run: |
          docker run --rm -v "$PWD":/mnt koalaman/shellcheck:stable \
            scripts/install-cp.sh \
            scripts/install-daemon.sh \
            control-plane/docker-entrypoint.sh

  build-daemon:
    name: Cross-compile daemon (all targets)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with:
          go-version: '1.22'
          cache-dependency-path: daemon/go.sum
      - name: Build all targets
        run: make build-all
      - name: Verify 4 binaries
        run: |
          ls dist/maestrod-linux-amd64 dist/maestrod-linux-arm64 \
             dist/maestrod-darwin-amd64 dist/maestrod-darwin-arm64
```

- [ ] **Step 2: Commit and push to a branch; verify CI runs**

Push the branch to GitHub and open a PR (or watch the push run). All four jobs should pass.

If you can't push yet (e.g., no PR branch), defer verification to the next time a PR is opened. Before deferring, at minimum verify the workflow parses:

Run (locally, if `actionlint` is installed): `actionlint .github/workflows/ci.yml`
Or on-line: `curl -s https://raw.githubusercontent.com/rhysd/actionlint/main/scripts/download-actionlint.bash | bash && ./actionlint`

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add CI workflow (go test, pytest, ruff, shellcheck, cross-compile)"
```

---

## Task 9: Release workflow

**Files:**
- Create: `.github/workflows/release.yml`

**Why:** On tag `v*`, we want a reproducible release that produces: 4 daemon binaries, SHA256SUMS, multi-arch CP image on GHCR, the two installer scripts from the tag, and GitHub attestations for provenance. No manual steps.

- [ ] **Step 1: Create the workflow**

Create `.github/workflows/release.yml`:

```yaml
name: Release

on:
  push:
    tags:
      - 'v*'

permissions:
  contents: write
  packages: write
  id-token: write
  attestations: write

jobs:
  build-binaries:
    name: Build binaries
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with:
          go-version: '1.22'
          cache-dependency-path: daemon/go.sum
      - name: Cross-compile
        env:
          VERSION: ${{ github.ref_name }}
        run: make build-all VERSION=${VERSION}
      - name: Generate checksums
        run: make checksums
      - name: Upload artifacts
        uses: actions/upload-artifact@v4
        with:
          name: binaries
          path: dist/
      - name: Attest binaries
        uses: actions/attest-build-provenance@v1
        with:
          subject-path: |
            dist/maestrod-linux-amd64
            dist/maestrod-linux-arm64
            dist/maestrod-darwin-amd64
            dist/maestrod-darwin-arm64

  build-image:
    name: Build & push CP image
    needs: build-binaries
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up QEMU
        uses: docker/setup-qemu-action@v3
      - name: Set up Buildx
        uses: docker/setup-buildx-action@v3
      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - name: Build & push
        id: push
        uses: docker/build-push-action@v5
        with:
          context: .
          file: control-plane/Dockerfile
          platforms: linux/amd64,linux/arm64
          push: true
          build-args: |
            VERSION=${{ github.ref_name }}
          tags: |
            ghcr.io/enzinobb/maestro-cp:${{ github.ref_name }}
            ghcr.io/enzinobb/maestro-cp:latest
      - name: Attest image
        uses: actions/attest-build-provenance@v1
        with:
          subject-name: ghcr.io/enzinobb/maestro-cp
          subject-digest: ${{ steps.push.outputs.digest }}
          push-to-registry: true

  release:
    name: Publish GitHub Release
    needs: [build-binaries, build-image]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Download binaries
        uses: actions/download-artifact@v4
        with:
          name: binaries
          path: dist/
      - name: Create release
        uses: softprops/action-gh-release@v2
        with:
          files: |
            dist/maestrod-linux-amd64
            dist/maestrod-linux-arm64
            dist/maestrod-darwin-amd64
            dist/maestrod-darwin-arm64
            dist/SHA256SUMS
            scripts/install-cp.sh
            scripts/install-daemon.sh
          generate_release_notes: true
```

- [ ] **Step 2: Verify the workflow parses**

Run `actionlint .github/workflows/release.yml` if available; otherwise validate via GitHub's YAML linter by opening the file in GitHub web UI (doesn't run the workflow until a tag is pushed).

- [ ] **Step 3: Dry-run plan**

The first real run happens when we push `v0.1.0` (out of scope for this plan — that's a maintainer action). Before tagging, verify locally that:
- `make build-all` produces the 4 binaries.
- `make build-image` builds the image.
- `docker run ghcr.io/enzinobb/maestro-cp:dev …` serves `/healthz`.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: add release workflow (binaries, multi-arch image, GH release, attestations)"
```

---

## Task 10: README quickstart rewrite

**Files:**
- Modify: `README.md:22-79`

**Why:** The existing README walks the reader through building from source. Layer 1 delivers a one-liner install — the quickstart must reflect that, with "build from source" moved to a "For contributors" section.

- [ ] **Step 1: Replace the quickstart block**

Modify `README.md`. Find the lines from `## Quick start` to the end of the `### 4. Deploya` block (everything before `## Struttura del repository`), and replace with:

````markdown
## Quick start

### 1. Avvia il control plane (una macchina)

```bash
curl -fsSL https://github.com/EnzinoBB/Maestro/releases/latest/download/install-cp.sh \
  | sudo bash
```

L'installer verifica/installa Docker, avvia il container, attende l'healthcheck.
Recupera il token generato al primo avvio:

```bash
docker compose -f /opt/maestro-cp/docker-compose.yml logs control-plane \
  | grep -A1 "GENERATED MAESTRO DAEMON TOKEN"
```

UI: `http://<cp-host>:8000`.

### 2. Installa un daemon (su ciascun host target)

Se il CP ha un dominio raggiungibile dall'host target:

```bash
curl -fsSL https://<cp-host>/install-daemon.sh | sudo bash -s -- \
  --host-id api-01 --token <TOKEN>
```

Oppure da GitHub (con `--cp-url` esplicito):

```bash
curl -fsSL https://github.com/EnzinoBB/Maestro/releases/latest/download/install-daemon.sh \
  | sudo bash -s -- --cp-url https://<cp-host> --host-id api-01 --token <TOKEN>
```

Supportato: Linux x86_64/arm64 (systemd), macOS x86_64/arm64 (launchd).

Il daemon scarica il binario dal CP (fallback GitHub), verifica lo SHA256,
installa il service systemd/launchd e si connette al CP.

### 3. Deploya

Apri la UI, incolla un `deployment.yaml` (vedi `examples/deployment.yaml`),
premi **Validate**, **Diff**, poi **Apply**. Oppure via API:

```bash
curl -X POST http://<cp-host>:8000/api/config/apply \
  -H 'content-type: text/yaml' \
  --data-binary @examples/deployment.yaml
```

### Per contributori — build da sorgente

```bash
make build-all              # cross-compile maestrod (linux+darwin × amd64+arm64)
make build-image            # build locale dell'immagine CP
make build-control-plane    # sanity check del CP Python
```

Per lo sviluppo locale del CP senza Docker:

```bash
cd control-plane
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/uvicorn app.main:app --port 8000 --reload
```
````

- [ ] **Step 2: Verify markdown renders**

Run: `grep -n '^##' README.md`
Expected: consistent header hierarchy, no broken sections.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: rewrite README quickstart around one-liner installers"
```

---

## Task 11: Release checklist

**Files:**
- Create: `docs/release-checklist.md`

**Why:** Cutting a release is rare enough that the maintainer shouldn't have to reconstruct the steps from memory. A checklist reduces release anxiety and ensures `playmaestro.cloud` stays in sync.

- [ ] **Step 1: Write the checklist**

Create `docs/release-checklist.md`:

```markdown
# Release Checklist

This document guides a maintainer through cutting a Maestro release. Automation
does the heavy lifting; the checklist exists to catch the things automation
can't verify.

## Preconditions

- [ ] `main` is green on CI.
- [ ] Local working tree is clean and on `main`: `git status` shows no changes.
- [ ] You've pulled: `git pull --ff-only origin main`.
- [ ] `CHANGELOG.md` (if maintained) is updated with user-facing changes since the last tag.

## Local verification

- [ ] `make test-unit` passes.
- [ ] `make build-all && make checksums` succeeds; `dist/` contains 4 binaries + `SHA256SUMS`.
- [ ] `make build-image` succeeds and the resulting container starts: `docker run --rm -p 18000:8000 ghcr.io/enzinobb/maestro-cp:dev &` then `curl http://localhost:18000/healthz` returns `{"ok":true}`.
- [ ] `shellcheck scripts/install-cp.sh scripts/install-daemon.sh control-plane/docker-entrypoint.sh` is clean.

## Tag and push

- [ ] Pick the next semver tag. For a bugfix release: `vX.Y.Z+1`. For a feature: `vX.Y+1.0`.
- [ ] `git tag -a vX.Y.Z -m "Release vX.Y.Z"`.
- [ ] `git push origin vX.Y.Z`.

## Automated release

Watch the Actions tab. The `Release` workflow should:

- [ ] Build all 4 binaries.
- [ ] Build the multi-arch image and push `ghcr.io/enzinobb/maestro-cp:vX.Y.Z` + `:latest`.
- [ ] Create a GitHub Release with binaries + `SHA256SUMS` + both installer scripts.
- [ ] Emit build attestations for binaries and image.

Total runtime should be 5–10 minutes.

## Post-release

- [ ] Smoke-test the published release from a clean VM:
  ```
  curl -fsSL https://github.com/EnzinoBB/Maestro/releases/download/vX.Y.Z/install-cp.sh | sudo bash
  ```
- [ ] Upgrade the reference CP on `playmaestro.cloud`:
  ```
  ssh admin@playmaestro.cloud sudo /opt/maestro-cp/install-cp.sh --upgrade
  ```
  (If the script was removed from the install dir, re-download: `curl -fsSL https://github.com/EnzinoBB/Maestro/releases/download/vX.Y.Z/install-cp.sh | sudo bash -s -- --upgrade`.)
- [ ] Verify `https://playmaestro.cloud/dist/maestrod-linux-amd64` returns the new binary (checksum matches the release).
- [ ] Announce the release: README already links to `releases/latest`; no code change needed unless there's a migration note.

## Rollback

- [ ] Pin the previous tag: `curl -fsSL …/vX.Y.Z-1/install-cp.sh | sudo bash -s -- --upgrade --version vX.Y.Z-1`.
- [ ] Document the reason in a GitHub issue and draft a fix.
```

- [ ] **Step 2: Commit**

```bash
git add docs/release-checklist.md
git commit -m "docs: add release checklist for maintainers"
```

---

## Self-Review Results

Performed against the spec [`docs/superpowers/specs/2026-04-22-installer-scripts-design.md`](../specs/2026-04-22-installer-scripts-design.md) §9.4.

**Spec coverage:**

| §9.4 component | Covered by |
|---|---|
| 1. CI / release pipeline | Tasks 8, 9 |
| 2. CP image changes (entrypoint, `/dist` bundle) | Tasks 3, 5 |
| 3. CP static endpoints | Task 4 |
| 4. `install-cp.sh` | Task 6 |
| 5. `install-daemon.sh` minimal | Task 7 |
| 6. Daemon darwin platform support | Task 1 |
| 7. Docs | Tasks 10, 11 |
| Makefile cross-compile | Task 2 (derived from Task 5 Dockerfile needs) |

**Type/identifier consistency:**
- `DEFAULT_CP_URL=""` placeholder: written in Task 7 Step 1, matched by replacement in Task 4 Step 3, verified in Task 7 Step 3. Consistent.
- Image name `ghcr.io/enzinobb/maestro-cp`: consistent in Tasks 2, 5, 6, 9, 11.
- `/opt/maestro-cp/dist`, `/opt/maestro-cp/scripts`: consistent in Tasks 4, 5.
- `maestrod-<os>-<arch>` binary naming: consistent in Tasks 2, 4, 5, 7, 8, 9.

**Placeholder scan:** no `TBD`, `TODO`, or "handle appropriately" strings in task bodies. Every code block is complete.

**Scope check:** all tasks belong to Layer 1. Layer 2 (enrollment backend, UI, enrollment-flavored `install-daemon.sh`) is explicitly deferred to Phase 3 per spec §9.2.

---

## Execution notes

- Task 1 and Task 2 are independent — can be interleaved or parallelized.
- Tasks 3 → 4 → 5 have a dependency chain (entrypoint → router → Dockerfile).
- Task 6 and Task 7 are independent of each other but both need Task 5's bundled binaries for end-to-end tests.
- Tasks 8, 9 can be written any time but the release workflow only fires on tags — first tag is a separate, maintainer-only action outside this plan.
- Tasks 10, 11 should come last once the actual flags/endpoints are verified.
