# Architecture

This document describes the general architecture of Maestro.
It is the primary reference for anyone — human or agent — working on the code.

## 1. Goals and non-goals

### Goals

- Allow an AI agent to pilot deployment, configuration, and startup of
  multi-component projects across multiple machines through a simple YAML
  schema.
- Reduce the agent's token usage by exposing high-level primitives
  (well-defined verbs, structured responses, classified errors) instead of
  requiring reasoning over raw shell output.
- Support idempotent deployments: only changed components are redeployed
  or restarted.
- Support multiple runtime types: systemd-managed processes, Docker
  containers, Kubernetes manifests (from Phase 3).
- Integrate with Git for a reactive CI/CD workflow (Phase 2).
- Expose a web user interface for configuration editing and state
  observation.
- Expose an MCP server so any compatible agent can operate on the system.

### Non-goals

- Not intended to replace Ansible, Terraform, Puppet, or Chef on complex
  enterprise projects. The goal is to comfortably cover small-to-medium
  projects.
- Not intended to be a multi-tenant SaaS system. It is designed to be
  installed and used by a single organization.
- Does not handle provisioning of the machines themselves (VM creation,
  networking, firewall). It assumes machines are already reachable over
  the network.

## 2. Three-tier architecture

```
                    ┌─────────────────────────────────────┐
                    │          Utente / Agente AI         │
                    └────┬────────────┬───────────────────┘
                         │            │
                 HTTP/WS │            │ MCP (JSON-RPC)
                         │            │
                    ┌────▼────────────▼───────────────────┐
                    │         Control Plane (Python)      │
                    │                                     │
                    │  ┌───────────┐  ┌─────────────────┐ │
                    │  │  Web UI   │  │   MCP Server    │ │
                    │  └─────┬─────┘  └────────┬────────┘ │
                    │        │                 │          │
                    │  ┌─────▼─────────────────▼────────┐ │
                    │  │   Orchestrator & State Hub     │ │
                    │  └────────────────┬───────────────┘ │
                    │                   │                 │
                    │  ┌────────────────▼───────────────┐ │
                    │  │   WebSocket Hub (per daemon)   │ │
                    │  └────────────────┬───────────────┘ │
                    └───────────────────┼─────────────────┘
                                        │
                         WebSocket (TLS, mutual-auth token)
                                        │
        ┌───────────────────────────────┼────────────────────────────┐
        │                               │                            │
   ┌────▼────┐                    ┌─────▼────┐                 ┌─────▼────┐
   │maestrod │                    │ maestrod │                 │ maestrod │
   │ host A  │                    │  host B  │                 │ host C   │
   └────┬────┘                    └─────┬────┘                 └─────┬────┘
        │                               │                            │
   ┌────▼──────────┐              ┌─────▼─────────┐           ┌──────▼────┐
   │ systemd units │              │  containers   │           │ systemd + │
   │               │              │   (Docker)    │           │  docker   │
   └───────────────┘              └───────────────┘           └───────────┘
```

### Control plane

Python service (FastAPI). Responsibilities:

- Read, validate, persist, and version `deployment.yaml` files.
- Maintain the registry of connected hosts and desired components.
- Compute the diff between desired state and observed state.
- Orchestrate deployments with the configured strategy (sequential in
  Phase 1, canary/blue-green from Phase 2).
- Expose a REST API for the UI and an MCP server for agents.
- Manage the WebSocket hub toward the daemons.
- Centralize logs and metrics received from the daemons.

### Daemon (maestrod)

Static Go binary installed as a systemd service on each host. Responsibilities:

- Open an outbound WebSocket connection to the control plane on startup,
  authenticating with a token.
- Maintain a local store (SQLite) with the current state: installed
  components, deployed revision, applied config, PID/container ID,
  runtime state, last healthcheck.
- Execute the actions requested by the control plane through the
  appropriate runners.
- Publish unsolicited events (drift, crash, failed healthchecks) and
  periodic metrics.
- Manage the lifecycle of processes locally, including retries on
  transient errors.

### AI agent

Not part of the code we produce — it is Claude (or another LLM) talking to
the control plane via MCP. Its behavior is guided by the skill in `skill/`,
which instructs it on the correct flow (validate → diff → confirm → apply →
watch → verify) and on handling classified errors.

## 3. Communication model

### Control plane ↔ daemon

The daemon opens a single outbound WebSocket toward the control plane. This
eliminates the need to open inbound ports on the hosts and is friendly to
firewalls/NAT.

Detailed protocol in `protocol.md`. In summary:

- JSON messages with an envelope `{id, type, payload}`.
- Requests from the control plane with a unique id; the daemon replies with
  the same id.
- The daemon publishes asynchronous events (`event.drift`,
  `event.healthcheck_failed`, `event.metrics`) with a dedicated type.
- Bidirectional heartbeat every 15 seconds; timeout at 45 seconds.
- Automatic reconnection with exponential backoff and jitter.

### Agent ↔ control plane (MCP)

MCP server exposed by the control plane, with the following verbs:

- `list_hosts`, `get_host_state`
- `list_components`, `get_component_state`
- `get_config`, `validate_config`, `apply_config`
- `deploy` (with target: host, component, or whole project), `rollback`
- `start`, `stop`, `restart`
- `run_tests`
- `tail_logs`, `get_metrics`
- `get_deployment_history`

All verbs return structured objects. Errors have a taxonomy
(`validation_error`, `dependency_missing`, `auth_error`, `runtime_error`,
`timeout`, `conflict`, `not_found`) with `suggested_fix` where applicable.

### User ↔ control plane

- Web UI (browser): pages for dashboard, YAML editor, log streaming,
  deployment history.
- REST API parallel to MCP, used by the UI.

## 4. State model and idempotency

The state of a deployed component is a triple:

```
component_hash = sha256(git_commit || rendered_config || build_artifact_hash)
```

For each deployment:

1. The control plane computes the desired `component_hash`.
2. It asks the daemon for the current `component_hash`.
3. If they match, no-op (the component is stable).
4. If they differ, the daemon performs the deployment according to the
   `deploy_mode` declared in the YAML (`hot`, `cold`, `blue_green`), then
   updates its store with the new hash.

This guarantees:

- **Idempotency**: a second run with the same input has no effect.
- **Selective deployment**: only components whose hash changed are touched.
- **Deterministic rollback**: the daemon keeps a history of the last N hashes
  and can revert to a previous one.

## 5. Per-component deployment modes

```yaml
deploy_mode: hot | cold | blue_green
```

- **hot**: zero-downtime update. The runner knows how to reload without
  stopping (e.g. `systemctl reload`, a container with `--recreate` and a
  healthcheck, a binary that handles `SIGHUP`). Only possible if declared
  by the component.
- **cold**: stop → deploy → start. Involves downtime but is universal.
- **blue_green**: the new version is installed in parallel, healthchecked,
  then traffic is switched and the old version torn down. Requires a load
  balancer or proxy in front.

## 6. Credentials and security

### Phase 1

Credentials stored in a `credentials.yaml` file encrypted with a master key
derived from a user passphrase (scrypt), kept in cleartext only in the
control plane's RAM. Supported credentials are:

- SSH/token for Git access (used by the control plane to clone repositories).
- Component secrets (env vars) — transmitted to daemons over WebSocket at
  deploy time, never persisted in cleartext on the daemon's disk.
- Daemon registration token (pre-shared).

### Phase 2+

A `credentials` module with a pluggable interface:

- Locally encrypted file (default).
- HashiCorp Vault integration.
- AWS Secrets Manager / GCP Secret Manager / Azure Key Vault integration.

Git credentials and application secrets are conceptually distinct but pass
through the same interface.

## 7. Git / CI-CD integration

From Phase 2, an internal control-plane component called **git-sync**:

- Receives webhooks (GitHub, GitLab, Gitea, Bitbucket) configured on the
  component repositories.
- Alternatively, runs configurable polling (5-minute default).
- On receiving a new commit on the tracked ref, marks the component as
  "drift detected" and, according to policy, automatically deploys or
  notifies the agent/user.
- Resolves `ref: main` to a concrete commit hash before passing it to the
  daemon.

## 8. Tests and verification

### Test framework (Phase 2)

Each component in the YAML can declare tests:

```yaml
tests:
  unit:
    command: npm test
    when: pre_deploy      # blocks the deploy on failure
  integration:
    command: npm run test:integration
    when: post_deploy
    requires: [db, redis]
  smoke:
    http: GET /health
    expect: 200
    when: post_deploy
```

The daemon runs the tests in the component's working directory and reports
the result as a structured event. On failure of a blocking test, the control
plane triggers a rollback.

### Testing the product itself

Layered across three levels:

- **Control plane unit tests**: `pytest`, WebSocket-client mocks, coverage
  of YAML parser, orchestrator, and validator modules.
- **Daemon unit tests**: standard Go tests (`go test`), with runner mocks.
- **Integration tests**: tests that spin up a real control plane + daemon
  (or multiple daemons) in-process, use supporting Docker containers, and
  verify end-to-end flows (validate → apply → deploy → healthcheck →
  rollback).

Each phase document includes an "Acceptance tests" section that the agent
responsible for development must execute autonomously before declaring the
phase complete.

## 9. Reasoned technical choices

| Area | Choice | Rationale |
|------|--------|-----------|
| Daemon | Go | Static single-file binary, easy distribution on any Linux, low RAM footprint, goroutines optimal for WS + managed processes |
| Control plane | Python (FastAPI) | Mature ecosystem for MCP, Claude SDK integration, rapid development, flexible UI stack |
| Daemon store | SQLite | Zero dependencies, transactional, suitable for small local datasets |
| Control-plane store | SQLite (Phase 1) → PostgreSQL (Phase 3) | Trivial migration via SQLAlchemy; SQLite is enough to iterate |
| Transport | WebSocket over TLS | Bidirectional, NAT-friendly, well handled by both ecosystems |
| UI | React + Vite (Phase 2) / HTMX (Phase 1) | Phase 1 minimal and light; Phase 2 introduces rich components |
| MCP auth | Bearer token per client | MCP standard, simple to manage |
| Daemon auth | Pre-shared token + mutual TLS (Phase 3) | Pre-shared is enough for Phase 1/2; mTLS added in Phase 3 for production |

## 10. Code structure

### Control plane (`control-plane/`)

```
app/
├── main.py               FastAPI app, startup, uvicorn entry
├── api/                  REST endpoints for the UI
│   ├── hosts.py
│   ├── components.py
│   ├── config.py
│   └── deploy.py
├── ws/                   WebSocket hub
│   ├── hub.py            Registry of active connections
│   ├── protocol.py       Message definitions (pydantic models)
│   └── handler.py        Dispatch of incoming messages
├── mcp/                  MCP server
│   ├── server.py
│   └── tools.py          Verb → orchestrator-function mapping
├── orchestrator/         Business logic
│   ├── engine.py         Deployment engine, rollout management
│   ├── diff.py           Desired-vs-observed diff computation
│   ├── rollback.py
│   └── tests_runner.py   (Phase 2)
├── config/               YAML parser
│   ├── schema.py         Pydantic schema models
│   ├── loader.py
│   ├── validator.py
│   └── renderer.py       Template rendering (Jinja2)
└── credentials/          Credential store
    ├── vault.py          Interface
    └── file_backend.py   Encrypted-file backend

tests/
├── unit/
│   ├── test_config_parser.py
│   ├── test_diff.py
│   ├── test_orchestrator.py
│   └── test_credentials.py
└── integration/
    ├── test_ws_handshake.py
    ├── test_deploy_flow.py
    └── test_mcp_tools.py
```

### Daemon (`daemon/`)

```
cmd/maestrod/
└── main.go               Entry point, flag parsing, lifecycle

internal/
├── config/               Daemon local config (endpoint, token)
├── ws/                   WebSocket client
│   ├── client.go
│   ├── protocol.go
│   └── reconnect.go
├── state/                Local store
│   ├── store.go          Interface
│   └── sqlite.go
├── runner/               Executors by type
│   ├── runner.go         Interface
│   ├── systemd.go
│   └── docker.go
├── metrics/              Metric collector
│   ├── collector.go
│   └── system.go
└── orchestrator/         Local mini-orchestrator (retry, lifecycle)
    └── lifecycle.go

test/integration/
├── systemd_runner_test.go
├── docker_runner_test.go
└── ws_roundtrip_test.go
```

By Go convention, unit tests sit alongside the code (`foo_test.go` next to
`foo.go`).

### Cross-component tests (`tests/`)

```
e2e/
├── test_full_deploy.py        Spins up control plane + one real daemon, full deploy
├── test_idempotency.py        Verifies that a second apply is a no-op
├── test_rollback.py           Simulates a failure and verifies rollback
└── test_multi_host.py         Two daemons, components distributed across them

fixtures/
├── deployment-simple.yaml
├── deployment-multihost.yaml
└── components/                Fake repositories used in the tests
```

## 11. Lifecycle of a typical deployment

1. User modifies `deployment.yaml` via the UI.
2. UI calls `POST /config/validate` → the control plane validates the
   schema and returns any errors.
3. If valid, the UI calls `POST /config/diff` → the control plane shows
   which components will change.
4. User confirms, the UI calls `POST /deploy`.
5. The orchestrator determines the order (topological over dependencies)
   and, for each component:
   a. Resolves the required credentials.
   b. If a Git clone is needed, performs it in the control plane's workspace.
   c. Renders config templates with the variables.
   d. Sends the target daemon a `deploy` message with the full payload.
   e. Waits for the reply; the daemon runs, tests locally, and responds.
   f. Waits for a positive healthcheck.
6. When all components are green, the operation is marked complete.
7. On failure of a step, the control plane attempts rollback of the
   components already deployed in the same session.

## 12. Observability

- Structured logs (JSON) on stdout for daemon and control plane.
- Prometheus metrics exposed by the control plane (deploys per minute,
  duration, failure rate, number of connected hosts).
- Per-component metrics collected by the daemons (CPU, RAM, restart count,
  uptime) and published over the WebSocket channel.
- Persistent audit log of all human and agent actions on the control plane.

## 13. Planned evolution

See `roadmap.md` for the phase breakdown. In summary:

- **Phase 1 (Prototype)**: working vertical slice, Linux/systemd/Docker,
  YAML v1, minimal UI, basic MCP, no Git-sync, no K8s.
- **Phase 2 (Beta)**: Git-sync, test framework, credential vault, rollback/hot,
  complete MCP, rich UI, mature skill.
- **Phase 3 (Production)**: Kubernetes, advanced observability, HA, CLI,
  packaging, complete user documentation.
