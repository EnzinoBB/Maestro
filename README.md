# Maestro

Multi-host deployment orchestrator driven by an AI agent — simpler than
Ansible for common cases, with a Python control plane (CP) and one Go
daemon per managed host.

A YAML file describes hosts, components, and their assignments. The CP
reads the YAML and coordinates the daemons, which know the local state,
execute the deploys, and stream metrics and logs back. An LLM agent
(Claude Code, Cursor, Copilot, …) talks to the CP via MCP; a bundled
[`SKILL.md`](skill/SKILL.md) teaches it the conventions.

## Project status — v0.3.2

| Layer | Status |
|---|---|
| Control plane (FastAPI + SQLite + WebSocket hub) | shipping |
| React + Vite SPA dashboard | shipping |
| Multi-user auth + RBAC (admin / operator) | shipping (M5–M7) |
| Daemon enrollment via in-browser wizard | shipping (v0.3.0) |
| User management UI (add user, change pw, reset pw) | shipping (v0.3.0) |
| Sidebar nav link to `/admin` for admins | shipping (v0.3.1) |
| Clipboard copy on plain-HTTP CP dashboards | fixed (v0.3.2) |
| Postgres backend, Kubernetes runner, mTLS | planned (Phase 3) |

The Phase 1 acceptance criteria are documented in
[`docs/phase-1-completion.md`](docs/phase-1-completion.md). Phase 2/3
plans are in [`docs/phase-2-beta.md`](docs/phase-2-beta.md) and
[`docs/phase-3-production.md`](docs/phase-3-production.md).

## Quick start

### 1. Install the control plane

On a host you can reach from your laptop:

```bash
curl -fsSL https://github.com/EnzinoBB/Maestro/releases/latest/download/install-cp.sh \
  | sudo bash
```

The installer:
- installs Docker + Compose v2 (with apt/dnf/yum fallbacks),
- pulls the CP image and starts the container,
- waits for the healthcheck on `:8000`,
- writes a systemd timer (`maestro-cp-update.timer`) that pulls newer
  releases nightly. Disable with `sudo systemctl disable --now
  maestro-cp-update.timer` if you prefer to upgrade manually.

If the CP sits behind a reverse proxy (nginx/Caddy/traefik with TLS),
set `MAESTRO_PUBLIC_URL=https://your-domain` in
`/opt/maestro-cp/docker-compose.yml`. It is used to compose the public
URL printed in the daemon installer scripts served from
`/install-daemon.sh`.

### 2. First-run setup (in the browser)

Open `http://<cp-host>:8000`. Because `MAESTRO_SINGLE_USER_MODE=false`
is the installer default, the CP refuses anonymous traffic and shows
the **first-run setup** form: pick an admin username + passphrase and
submit. You land on the dashboard signed in as that user.

If you prefer the legacy unauthenticated mode (development only — the
CP becomes accessible to anyone who can reach the port), set
`MAESTRO_SINGLE_USER_MODE=true` and restart.

### 3. Enroll a daemon (in the browser)

In the SPA, **Nodes → Enroll new daemon** (admins only) opens a 4-step
drawer wizard:

1. **Identity** — pick a `host_id` and an optional human label.
2. **Install** — copy the prebuilt `curl … | sudo bash` command (it
   already embeds the CP URL and the freshly issued enrollment token).
3. **Waiting** — the wizard polls `/api/nodes` until the daemon
   actually connects.
4. **Confirm** — green check; the new node is now visible in `/nodes`.

The CLI flow still works for scripted setups:

```bash
curl -fsSL https://<cp-host>/install-daemon.sh | sudo bash -s -- \
  --host-id api-01 --token <TOKEN>
```

Or, when DNS to the CP isn't set up yet, fetch the installer from
GitHub and pass `--cp-url` explicitly:

```bash
curl -fsSL https://github.com/EnzinoBB/Maestro/releases/latest/download/install-daemon.sh \
  | sudo bash -s -- --cp-url https://<cp-host> --host-id api-01 --token <TOKEN>
```

Supported: Linux x86_64/arm64 (systemd), macOS x86_64/arm64 (launchd).
The daemon downloads its binary from the CP (with a GitHub fallback),
verifies the SHA256, installs the systemd/launchd unit, and connects.

### 4. Deploy

You have three equivalent paths. Pick the one that fits the moment:

- **Wizard** (most users) — `Wizard` in the sidebar walks you through
  Source → Placement → Runtime → Review and creates the deploy
  end-to-end. It generates the `deployment.yaml` for you.
- **YAML** (power users) — write `deployment.yaml` (see
  [`examples/deployment.yaml`](examples/deployment.yaml) and
  [`docs/yaml-schema.md`](docs/yaml-schema.md)) and submit it through
  the Deploys screen. The CP runs **Validate → Diff → Apply**.
- **API / agent** — `POST /api/deploys` with the YAML body, then
  `POST /api/deploys/{id}/{validate,diff,apply}`. An MCP-capable agent
  uses the same surface via the `maestro_*` verbs from
  [`skill/SKILL.md`](skill/SKILL.md).

A side-by-side guide that shows YAML and the equivalent UI/API for each
field is published at
[`website/guide.html`](website/guide.html) (also reachable from the
landing page).

### 5. User management

In the SPA, **Admin** in the sidebar (admins only) lets you:

- create new users (inline form with `dns-1123` username validation +
  initial passphrase),
- reset a user's passphrase (auto-generates a `secrets.token_urlsafe`
  one-time string in a modal),
- change your own passphrase from the avatar popover (top right →
  **Change password**).

The first user (created via first-run setup) is automatically `admin`.
Subsequent users default to `operator` and can be promoted from the
admin screen.

### For contributors — build from source

```bash
make build-all              # cross-compile maestrod (linux+darwin × amd64+arm64)
make build-image            # local build of the CP image
make build-control-plane    # sanity check of the Python CP

# Local CP development without Docker:
cd control-plane
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/uvicorn app.main:app --port 8000 --reload

# Local SPA development with HMR:
cd web-ui
npm install
npm run dev          # serves on :5173 with /api proxied to :8000
```

## Repository structure

```
.
├── docs/                  Architecture, schema, and roadmap documentation
├── control-plane/         Python service (FastAPI + WebSocket hub + MCP)
│   ├── app/               Application code
│   └── tests/             Unit and integration tests
├── web-ui/                React + Vite SPA (built into the CP image)
│   ├── src/screens/       Routed pages (Overview, Deploys, Nodes, Wizard, Admin)
│   ├── src/components/    EnrollDrawer, UserMenuPopover, etc.
│   └── src/wizard/        Wizard state machine + YAML generator
├── daemon/                Host-side agent in Go (maestrod)
│   ├── cmd/maestrod/      Entry point
│   ├── internal/          Internal packages
│   └── test/integration/  Daemon integration tests
├── tests/                 Cross-component end-to-end tests
├── skill/                 SKILL.md + MCP schema for LLM agents
├── examples/              Example deployment.yaml files
├── website/               Public landing site + deployment guide
├── scripts/               Installation scripts (install-cp.sh, install-daemon.sh)
└── dist/                  Build artifacts (not versioned)
```

## Key documents

| File | Purpose |
|------|---------|
| [`docs/architecture.md`](docs/architecture.md) | General architecture, technical choices, state model |
| [`docs/yaml-schema.md`](docs/yaml-schema.md) | Formal schema of the `deployment.yaml` file |
| [`docs/protocol.md`](docs/protocol.md) | Control plane ↔ daemon WebSocket protocol |
| [`website/guide.html`](website/guide.html) | Side-by-side guide: YAML vs Control Plane |
| [`docs/roadmap.md`](docs/roadmap.md) | Overview of the three development phases |
| [`docs/phase-1-completion.md`](docs/phase-1-completion.md) | Phase 1 report: what was built + acceptance |
| [`docs/phase-2-beta.md`](docs/phase-2-beta.md) | Phase 2 instructions |
| [`docs/phase-3-production.md`](docs/phase-3-production.md) | Phase 3 instructions |
| [`skill/SKILL.md`](skill/SKILL.md) | Skill for LLM agents using the CP's MCP |

## Tests

```bash
make test-unit         # Python + Go unit
make test-integration  # Go integration (requires docker)
make test-e2e          # cross-component e2e (requires docker)

# SPA:
cd web-ui && npx tsc --noEmit && npx vite build
```

## License

Apache-2.0.
