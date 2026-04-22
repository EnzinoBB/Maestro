# Development roadmap

The project is planned in three incremental phases. Each phase produces a
usable artifact and is documented by a dedicated file (`phase-N-*.md`)
designed to be fed to an AI agent together with the code produced in
previous phases, enabling iterative development with low token usage.

## Phase summary

| Phase | Name | Goal | Estimated duration |
|-------|------|------|--------------------|
| 1 | Prototype | Working vertical slice: real deployment of a component from YAML | 1-2 weeks |
| 2 | Beta | Complete features: Git-sync, tests, rollback, credential vault, hot deploy, full MCP | 2-3 weeks |
| 3 | Production | Kubernetes, advanced observability, HA, CLI, packaging, user documentation | 2-3 weeks |

## Phase 1 — Prototype

**In scope:**
- YAML schema v1 (subset), parser, and validator.
- Go daemon with systemd and Docker runners, SQLite store, WebSocket client.
- Python control plane with FastAPI, WebSocket hub, sequential orchestrator,
  REST API for the UI.
- Minimal web UI (HTMX, one page: dashboard + YAML editor + logs).
- MCP server with the essential verbs.
- Skill skeleton.
- Unit tests on both sides + end-to-end integration tests that actually
  deploy a real Docker component.

**Out of scope:**
- Kubernetes, automatic Git-sync, component test framework, advanced
  credential vault, canary/blue-green rollouts, hot deploy.

**Deliverable**: runnable repository with `docker compose up` for the
control plane + `maestrod` installable on a Linux host; working end-to-end
deployment of `examples/deployment.yaml`.

## Phase 2 — Beta

**Adds:**
- Git-sync component (webhooks + polling) with automatic trigger on commit.
- Component test framework (pre/post deploy, unit/integration/smoke).
- Credential vault with encrypted-file backend and pluggable interface.
- Automatic rollback on failed tests/healthchecks.
- Hot deploy and blue_green for components that support them.
- Canary rollouts.
- Rich web UI (React) with log streaming, metric charts, deployment history.
- MCP server with all verbs.
- Complete skill with documented decision flows.

**Deliverable**: system usable daily for real multi-component projects.

## Phase 3 — Production

**Adds:**
- Kubernetes runner (Deployment/StatefulSet/Helm).
- Observability: Prometheus metrics, OpenTelemetry tracing, structured
  audit log.
- High availability of the control plane (PostgreSQL, cluster of instances
  with leader election).
- mTLS between daemon ↔ control plane.
- `maestro` CLI for terminal operations.
- Packaging: Docker image of the control plane on a registry, .deb/.rpm
  of the daemon, optional Helm chart.
- Complete user documentation (install guide, tutorial, API reference).
- Basic RBAC for UI and MCP (users, roles, permissions).

**Deliverable**: product ready for installation at an organization.

## Rules for transitioning between phases

A phase is considered complete when:

1. All tasks of the phase document are resolved.
2. All acceptance tests of the phase pass.
3. The system starts up and responds to the commands documented in the
   same file.
4. The phase documentation is updated to reflect any deviations from the
   initial plan.

If a technical choice from the plan turns out to be wrong during
implementation, the agent has a mandate to deviate, documenting the
deviation and the reasons in a `docs/deviations.md` file.

## How to feed the documents to an agent

For **Phase 1**: provide the agent with:
- `README.md`
- `docs/architecture.md`
- `docs/yaml-schema.md`
- `docs/protocol.md`
- `docs/phase-1-prototype.md`
- `examples/deployment.yaml`
- `skill/SKILL.md`

The agent will proceed from the empty directory tree to the completion of
Phase 1.

For **Phase 2**: provide the agent with the repository as it stands at the
end of Phase 1, plus:
- `docs/phase-2-beta.md`

For **Phase 3**: provide the repository at the end of Phase 2, plus:
- `docs/phase-3-production.md`

Each phase document is intentionally self-contained: it lists prerequisites,
tasks, acceptance criteria, and tests to run.
