# Maestro

Multi-host deployment orchestrator driven by an AI agent, designed to be
simpler than Ansible for common cases and to minimize token usage when an
LLM agent pilots operations.

## What it does

A YAML file describes hosts, components, and assignments. A Python control
plane reads the YAML and coordinates Go daemons running on each target host,
which know the local state, execute deployments, and report metrics and logs.
An AI agent (Claude or otherwise) interacts with the system via MCP, guided
by a skill that encodes the usage conventions.

## Current status

**Phase 1 (Prototype) complete.** The system is functional end-to-end on
Linux/systemd/Docker. See `docs/phase-1-completion.md` for the full status
report; the Phase 2/3 plans are in `docs/phase-2-beta.md` and
`docs/phase-3-production.md`.

## Quick start

### 1. Start the control plane (one machine)

```bash
curl -fsSL https://github.com/EnzinoBB/Maestro/releases/latest/download/install-cp.sh \
  | sudo bash
```

If the CP sits behind a reverse proxy (nginx/Caddy/traefik with TLS), set
`MAESTRO_PUBLIC_URL=https://your-domain` in the container environment: it
is used to correctly compose the public URL in the installer scripts
served from `/install-daemon.sh`.

The installer verifies/installs Docker, starts the container, and waits
for the healthcheck. Retrieve the token generated on first start:

```bash
docker compose -f /opt/maestro-cp/docker-compose.yml \
  exec control-plane cat /data/daemon-token
```

(Or from the first-start logs:
`docker compose -f /opt/maestro-cp/docker-compose.yml logs control-plane | grep -A1 "GENERATED MAESTRO DAEMON TOKEN"`.)

UI: `http://<cp-host>:8000`.

### 2. Install a daemon (on each target host)

If the CP has a domain reachable from the target host:

```bash
curl -fsSL https://<cp-host>/install-daemon.sh | sudo bash -s -- \
  --host-id api-01 --token <TOKEN>
```

Or from GitHub (with an explicit `--cp-url`):

```bash
curl -fsSL https://github.com/EnzinoBB/Maestro/releases/latest/download/install-daemon.sh \
  | sudo bash -s -- --cp-url https://<cp-host> --host-id api-01 --token <TOKEN>
```

Supported: Linux x86_64/arm64 (systemd), macOS x86_64/arm64 (launchd).

The daemon downloads the binary from the CP (GitHub fallback), verifies the
SHA256, installs the systemd/launchd service, and connects to the CP.

### 3. Deploy

Open the UI, paste a `deployment.yaml` (see `examples/deployment.yaml`),
press **Validate**, **Diff**, then **Apply**. Or via API:

```bash
curl -X POST http://<cp-host>:8000/api/config/apply \
  -H 'content-type: text/yaml' \
  --data-binary @examples/deployment.yaml
```

### For contributors — build from source

```bash
make build-all              # cross-compile maestrod (linux+darwin × amd64+arm64)
make build-image            # local build of the CP image
make build-control-plane    # sanity check of the Python CP
```

For local CP development without Docker:

```bash
cd control-plane
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/uvicorn app.main:app --port 8000 --reload
```

## Repository structure

```
.
├── docs/                  Architecture, schema, and roadmap documentation
├── control-plane/         Python service (FastAPI + WebSocket hub + MCP)
│   ├── app/               Application code
│   ├── tests/             Unit and integration tests
│   └── web/               User-facing web UI (HTMX)
├── daemon/                Host-side agent in Go (maestrod)
│   ├── cmd/maestrod/      Entry point
│   ├── internal/          Internal packages
│   └── test/integration/  Daemon integration tests
├── tests/                 Cross-component end-to-end tests
│   ├── e2e/
│   └── fixtures/
├── skill/                 Skill for agents that use the CP's MCP
├── examples/              Example deployment.yaml files
├── scripts/               Installation scripts
└── dist/                  Build artifacts (not versioned)
```

## Key documents

| File | Purpose |
|------|---------|
| `docs/architecture.md` | General architecture, technical choices, state model |
| `docs/yaml-schema.md` | Formal schema of the `deployment.yaml` file |
| `docs/protocol.md` | Control plane ↔ daemon WebSocket protocol |
| `docs/roadmap.md` | Overview of the three development phases |
| `docs/phase-1-completion.md` | Phase 1 report: what was built + acceptance criteria |
| `docs/phase-1-prototype.md` | Original Phase 1 instructions |
| `docs/phase-2-beta.md` | Phase 2 instructions |
| `docs/phase-3-production.md` | Phase 3 instructions |

## Tests

```bash
make test-unit         # Python + Go unit
make test-integration  # Go integration (requires docker)
make test-e2e          # cross-component e2e (requires docker)
```

## License

Apache-2.0.
