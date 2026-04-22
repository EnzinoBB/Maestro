# Phase 3 — Production

> **Instructions for the agent reading this document.**
> Assumes Phase 2 is complete and verified. Before starting, read:
> - `docs/architecture.md`
> - `docs/yaml-schema.md` (Phase 3 fields — Kubernetes)
> - `docs/protocol.md`
> - `docs/phase-1-completion.md` and `docs/phase-2-completion.md`
> - This document
>
> **There must be no regression**: run the entire Phase 1 and Phase 2
> acceptance suite as a first step and as a final step.

## 1. Goal of Phase 3

Take the system from beta to "installable at an organization with
confidence": add Kubernetes, observability, production-grade security, HA,
CLI, packaging, and user documentation.

**In scope:**
- Kubernetes runner (Deployment, StatefulSet, Helm).
- Prometheus metrics exposed by the control plane and the daemons.
- OpenTelemetry tracing with propagation between control plane and daemon.
- Structured audit log of all human and agent actions.
- Control-plane migration to PostgreSQL (with an upgrade path from SQLite).
- High availability: multiple control-plane instances behind an LB, leader
  election for the orchestrator, "sticky" or rebalanceable WS sessions.
- mTLS between daemon ↔ control plane with an internal CA.
- User authentication on the UI and the API (OIDC + API token), RBAC
  (roles: admin, operator, viewer) with granular permissions on projects.
- `maestro` CLI for terminal operations (deploy, status, logs, tests,
  rollback).
- Packaging: Docker image of the control plane published on a registry,
  .deb and .rpm packages of the daemon, optional Helm chart of the control
  plane.
- User documentation: install guides, tutorial, API/MCP reference,
  troubleshooting.

## 2. Prerequisites

- Repository at the completion of Phase 2 with all tests passing.
- Test Kubernetes cluster available (kind/k3d are fine).
- Account on a registry (Docker Hub, GHCR, ECR…) for the images.
- OpenSSL available (for the internal CA).

## 3. Operational checklist

### Group A — Kubernetes runner

A1. New host type in `yaml-schema.md`:
    ```yaml
    hosts:
      k8s-prod:
        type: kubernetes
        kubeconfig_ref: vault://kube/prod
        context: production
        namespace: default
    ```

A2. Architectural strategy: for Kubernetes targets, there is no daemon
    living in the cluster. The control plane instantiates a "K8s executor"
    that speaks to the Kubernetes API (client-go in a dedicated Go
    microservice invoked by the control plane, or the `kubernetes` Python
    client directly in the control plane). Evaluate the two options and
    pick based on where the logic most naturally lives; document the
    choice in `phase-3-completion.md`.

A3. `components.<id>.run.type: kubernetes` supports two subforms:
    - `manifest_template`: path to a Jinja2 template that produces one or
      more YAML manifests. The control plane renders them, applies with
      `kubectl apply` (or API), and waits for ready.
    - `helm`: chart path or reference, inline values or a values file.
      The control plane uses `helm upgrade --install` via subprocess or
      Python SDK.

A4. `healthcheck` for K8s targets: read `.status.readyReplicas` and
    compare against `spec.replicas`. For StatefulSets, also ordering.

A5. K8s rollback:
    - For manifests: reapply the previous version.
    - For Helm: `helm rollback`.

A6. Logs: tail the pods; aggregate logs from all pods of the same
    Deployment into the returned tail.

A7. Protocol message extension: the K8s executor does not use WebSocket
    (it is in-process to the control plane); but it exposes the same
    `Runner` interface so the orchestrator can treat K8s as any other
    host.

**Tests:**
- `test_k8s_runner_unit.py`: K8s client mock, verifies manifest
  translation and state management.
- `test_k8s_integration.py`: with a kind cluster, real deployment of an
  nginx Deployment (1 replica), healthcheck, rollback.

### Group B — Observability

B1. Prometheus metrics exposed by the control plane on `/metrics`:
    - `maestro_deploys_total{project, status}`
    - `maestro_deploy_duration_seconds{project, component}`
    - `maestro_hosts_connected`
    - `maestro_components_running{project, host}`
    - `maestro_rollbacks_total{reason}`
    - `maestro_ws_messages_total{direction, type}`
    - Histogram of healthcheck durations.

B2. Metrics exposed by the daemons on `/metrics` (optional port, disabled
    by default to avoid opening inbound ports; activatable via config):
    - Per-component system metrics already collected.
    - Metrics of the daemon itself (uptime, reconnections, queue depth).

B3. OpenTelemetry tracing:
    - Configurable OTLP export.
    - Trace context propagation through WebSocket messages (optional
      `trace_context` field in the envelope).
    - Main spans: `config.validate`, `deploy.component`, `build`,
      `runner.start`, `healthcheck.wait`.

B4. Structured audit log in `audit.log` (rotated JSONL file) with:
    - `actor_type: user|agent|system`
    - `actor_id`
    - `action`
    - `target`
    - `result: ok|error`
    - `ts`
    - `request_id`

B5. UI: new "Observability" page with links to external Prometheus
    dashboards or a Grafana embed if available. Audit log searchable via
    filters.

**Tests:**
- `test_metrics_exposition.py`: start the control plane, perform
  operations, verify that `/metrics` contains the expected counters with
  correct increments.
- `test_tracing_propagation.py`: generate a trace, verify spans on the
  control plane AND on the daemon (mocked collector).
- `test_audit_log.py`: every user/agent action produces a complete audit
  record.

### Group C — PostgreSQL migration

C1. Abstract DB access behind a repository/DAO. No direct SQLAlchemy
    usage scattered across modules (if any exists, refactor).

C2. Add a PostgreSQL backend while keeping the SQLite backend for dev.
    Selection via config: `database.url: postgresql://...` or
    `sqlite:///...`.

C3. Migration script `scripts/migrate-sqlite-to-postgres.py` that copies
    all data preserving the schema.

C4. Alembic for future schema migrations; introduce it now with the
    current baseline.

**Tests:**
- `test_db_backends.py`: the same tests run against both SQLite and
  PostgreSQL (via testcontainers). Functional parity.
- `test_migration.py`: dump SQLite, migrate, verify identical data in
  PostgreSQL.

### Group D — High availability

D1. The control plane can run as multiple instances behind a load
    balancer. Problems to solve:
    - **Sticky or rebalanceable WS sessions**: pick a strategy. The
      simplest: every daemon is "owned" by a specific instance
      (identified via consistent hashing on `daemon_id` → instance_id);
      if the instance dies, the daemon reconnects and another node picks
      it up.
    - **Leader election for stateful operations**: use a lease on the DB
      (PostgreSQL advisory lock or a `leader_lease` table). Only the
      leader runs the global git-sync poller, periodic cleanups,
      expirations.
    - **State sharing**: all persistent state goes to the DB; nothing in
      local memory except caches.

D2. Health endpoint `/healthz` considers the instance "ready" only if:
    - DB reachable.
    - Local WS hub operational.
    - (For the leader) leader lease renewed.

D3. Graceful shutdown:
    - Stop accepting new requests.
    - Close WS and instruct daemons to reconnect.
    - Complete ongoing orchestrations or yield the lease.

**Tests:**
- `test_ha_failover.py`: start 2 instances + 1 daemon; stop the instance
  that owns the connection; the daemon reconnects to the other within
  10s; operations resume.
- `test_leader_election.py`: 2 instances; only one runs the cron jobs;
  on killing the leader, the other takes the lease within 30s.

### Group E — Security

E1. Mutual TLS daemon ↔ control plane:
    - Script `maestro ca init` that generates a private CA and a server
      certificate for the control plane.
    - `maestro ca issue-daemon <host_id>` produces a signed keypair for a
      daemon.
    - **Certificate distribution channel to the daemon: enrollment protocol**
      (see `docs/superpowers/specs/2026-04-22-installer-scripts-design.md`,
      Layer 2). Layer 1 of that design — implemented before Phase 2 —
      distributes a shared token to the daemon via `POST /api/enroll/<token>/consume`;
      in Phase 3 the consume response is extended from `{daemon_token}` to
      `{daemon_cert, daemon_key, ca_cert}`. The admin uses the same UI
      "Add host" → enroll URL → `curl … | sudo bash` flow already available.
    - Rotation: the control plane can revoke (CRL in DB) and reissue.
    - TLS + token fallback remains available for backward compatibility,
      deprecated but functional.

E2. User authentication on UI/API:
    - OIDC (support for one provider: Keycloak, Auth0, Google… —
      configurable). At least one working implementation.
    - Static API tokens for integrations (MCP included). Tokens bound to
      a role.

E3. RBAC:
    - Predefined roles: `admin`, `operator`, `viewer`.
    - Per-resource permissions: `project.read`, `project.write`,
      `component.deploy`, `component.rollback`, `vault.read`,
      `vault.write`, `audit.read`.
    - Authorization enforced on every API endpoint and every MCP tool.

E4. Hardening:
    - Security headers on the UI (CSP, HSTS, X-Content-Type-Options).
    - Basic rate limiting on public endpoints.
    - Secrets never logged (allow-list of loggable fields).

E5. Enrollment backend (Layer 2 of the 2026-04-22 design):
    - Implement the `host_enrollments` table and Alembic migrations.
    - Implement endpoints `POST /api/enrollments`,
      `GET /api/enrollments`, `DELETE /api/enrollments/<token>`,
      `GET /enroll/<token>`, `POST /api/enroll/<token>/consume`.
      Full spec in `docs/superpowers/specs/2026-04-22-installer-scripts-design.md`
      §5.1-5.2.
    - Extend the consume response to include
      `{daemon_cert, daemon_key, ca_cert}` in addition to (or instead of)
      `daemon_token` (integrates with E1).
    - UI `/hosts` with "Add host" modal (design §5.3).
    - `install-daemon.sh` updated to the `curl …/enroll/<t> | sudo bash`
      flow as the canonical channel (design §5.4, full variant).
    - Authorization: `POST /api/enrollments` and `DELETE /api/enrollments/<t>`
      require `host.create` / `host.revoke` permission (integrates with E3 RBAC).
    - Audit: every creation / consume / revocation recorded (integrates with B4).
    - Backward compatibility: existing installations using shared `--token`
      keep working; the new enrollment channel is additive.

**Tests:**
- `test_mtls.py`: handshake with a valid cert, handshake rejected with
  a cert not signed by the CA, revocation working.
- `test_authn.py`: OIDC flow with a mocked provider, JWT validated.
- `test_rbac.py`: viewer cannot deploy, operator can deploy but not
  manage the vault, admin can do everything.
- `test_enrollment.py`: create enrollment, consume happy path, expired token
  → 410, already-consumed token → 410, `host_id_pattern` mismatch → 403,
  revocation working, complete audit record.

### Group F — CLI

F1. `maestro` binary (in Go for consistency with the daemon, or an
    installable Python wheel — choose and document). Commands:
    - `maestro config validate <file>`
    - `maestro config apply <file>`
    - `maestro deploy [--component X]`
    - `maestro status [--project P]`
    - `maestro logs <component> [--follow] [--lines N]`
    - `maestro rollback <component> [--steps N]`
    - `maestro tests run <component> [--type unit|integration|smoke|all]`
    - `maestro vault set/get/list/delete`
    - `maestro hosts list`

F2. Configuration via `~/.config/maestro/config.yaml` (control-plane
    endpoint, token).

F3. Output: human-readable text by default, `--json` for structured
    output.

**Tests:**
- `test_cli_unit.py` (or `cli_test.go`): argument parsing, request
  generation.
- `test_cli_e2e.py`: start the stack, the CLI runs a basic end-to-end
  flow equivalent to the UI.

### Group G — Packaging and distribution

G1. CI (GitHub Actions or equivalent) that:
    - Runs all tests.
    - Builds and publishes `ghcr.io/<org>/maestro-control-plane:<version>`. **[Already implemented in Layer 1 of the 2026-04-22 design as `ghcr.io/enzinobb/maestro-cp`.]**
    - Builds `maestrod` binaries for linux/amd64 and linux/arm64, publishes releases.
      **[Already implemented in Layer 1; Layer 1 also includes darwin/amd64 and darwin/arm64.]**
    - Builds `.deb` and `.rpm` packages for the daemon (via `nfpm` or
      `goreleaser`). **[New Phase 3 work.]**

G2. Helm chart in `deploy/helm/maestro-control-plane/` to install the
    control plane on Kubernetes with a PostgreSQL sidecar or an external
    connection.

G3. Template `docker-compose.prod.yml` as an alternative to the chart.

G4. Script `scripts/upgrade.sh` that upgrades existing installations
    (control plane in place + invocation of daemon self-update if
    required). **[The primitives `install-cp.sh --upgrade` and
    `install-daemon.sh --upgrade` are already available from Layer 1 of the
    2026-04-22 design; `upgrade.sh` in Phase 3 orchestrates them across a fleet.]**

### Group H — User documentation

H1. `docs/user/` contains:
    - `installation.md` (single-node, HA, Kubernetes).
    - `quickstart.md` (zero to first deploy in 10 minutes).
    - `yaml-reference.md` (complete schema coverage, examples).
    - `mcp-reference.md` (all MCP verbs with examples).
    - `api-reference.md` (generated OpenAPI + notes).
    - `cli-reference.md`.
    - `troubleshooting.md` (guide to common errors with `code` →
      solution).
    - `security.md` (security model, mTLS setup, certificate rotation).
    - `observability.md` (metrics, tracing, audit).

H2. Static documentation site generated with MkDocs or Docusaurus,
    published via CI.

### Group I — Skill hardening

I1. Update `skill/SKILL.md` with:
    - Kubernetes section: how to reason about K8s vs Linux targets.
    - RBAC section: how the agent's permission can constrain the
      available actions.
    - Examples of errors produced by the new features with recommended
      actions.
    - Patterns for cross-environment operations (dev/staging/prod) when
      the user has multiple projects.

## 4. Additional fixtures

- `tests/fixtures/deployment-k8s.yaml`
- `tests/fixtures/k8s-manifest-api.yaml.j2`
- `tests/fixtures/helm-chart-demo/` (minimal chart)
- `tests/fixtures/oidc-mock-config.yaml`

## 5. Phase 3 acceptance suite

### Acceptance 1 — Regression

All Phase 1 and Phase 2 acceptance tests pass.

### Acceptance 2 — Kubernetes deploy

- kind cluster running.
- `deployment-k8s.yaml` applied.
- Deployment created, pod ready, healthcheck positive.
- Rollback working.
- Logs readable via API/UI/CLI.

### Acceptance 3 — Observability

- `curl /metrics` of the control plane includes all expected metrics.
- A deploy generates a complete trace visible in the test collector.
- Audit log contains records for each simulated action.

### Acceptance 4 — HA

- Failover demonstrated (see group D tests).
- Leader election demonstrated.

### Acceptance 5 — Security

- mTLS enforced (rejects a daemon without a valid cert).
- RBAC enforced (viewer cannot deploy; test fails with 403).
- OIDC flow works with a mocked provider.
- Enrollment: from the UI `/hosts` an admin creates an enroll URL, a new host
  runs the one-liner `curl …/enroll/<t> | sudo bash`, the daemon registers
  with an mTLS cert received via consume, appears in `GET /api/hosts` as `active`;
  a second attempt with the same token returns 410.

### Acceptance 6 — PostgreSQL

- Stack started with `DATABASE_URL=postgresql://...` instead of SQLite.
- All Phase 1 and Phase 2 acceptance tests continue to pass.

### Acceptance 7 — CLI

- All documented CLI commands run correctly.
- `--json` output parseable.
- Permissions respected (CLI with a viewer token cannot deploy).

### Acceptance 8 — Packaging

- Control-plane Docker image runnable with `docker run`.
- Daemon binary installable from `.deb` on Ubuntu 22.04 in the test.
- Helm chart installable on kind with `helm install`.

### Acceptance 9 — Documentation

- Docs site builds clean, zero broken links (link checker in CI).
- Every error code documented in `troubleshooting.md`.
- At least one e2e tutorial (quickstart) walked through step-by-step by
  a human.

### Acceptance 10 — Performance and scale

- Idempotent deploy of 20 components distributed across 3 hosts
  completes in ≤ 3 minutes.
- Control plane sustains 50 daemons connected simultaneously with a
  memory footprint < 512 MB.
- `get_state` for a project with 20 components returns in ≤ 200 ms.

### Acceptance 11 — Token usage (agents)

- Automated test that measures: average number of tokens required by an
  agent to complete a typical workflow ("update API to commit X, verify
  healthcheck, rollback on failure"). Benchmark documented; target
  ≤ 30% relative to a "free shell" baseline (indicative; the measure is
  comparative).

## 6. Final documents

- `docs/phase-3-completion.md`: deviations, architectural choices made
  (e.g. K8s in-process vs microservice).
- `README.md` updated with CI badge, docs link, quickstart.
- `CHANGELOG.md` with all versions released during the phase.

## 7. Things to avoid in Phase 3

- Do not add features not listed here; any extensions (additional
  runners, multi-region, etc.) belong in a later phase.
- Do not compromise the simplicity of the core YAML to support K8s.
- Do not break compatibility with Phase 1/2 YAML files.

## 8. Quality criteria

- Test coverage ≥ 85% Python, ≥ 80% Go.
- Zero linter warnings in CI.
- Zero dependencies with known High- or Critical-level CVEs (scan with
  `trivy` or equivalent on the final image).
- Documentation with a clean spell check.
- All public APIs with OpenAPI and every MCP tool with documented
  input/output schema.
