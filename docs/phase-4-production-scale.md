# Phase 4 — Production Scale

> **Status:** planned.
> **Predecessor:** [phase-3-operational-maturity.md](phase-3-operational-maturity.md).
> **Goal:** make Maestro installable inside an organization with confidence — Kubernetes targets, Postgres, HA, mTLS, OIDC, CLI, professional packaging, full documentation, OpenTelemetry.

## 1. Scope

Phase 4 promotes the operationally complete CP from Phase 3 into a production-grade product: introduces Kubernetes as a first-class runner, swaps SQLite for Postgres for HA installations, adds leader election, replaces the daemon-token-only auth channel with mTLS, layers OIDC over the Phase-3 RBAC, ships a `maestro` CLI for terminal operators, professional packaging (.deb / .rpm / Helm chart), a documentation site, and OpenTelemetry tracing. **No regression** of any Phase 1/2/3 acceptance test.

## 2. Prerequisites

- Repository at the state of `phase-3-completion.md` (to be produced at end of Phase 3).
- Test Kubernetes cluster (kind / k3d acceptable).
- Container registry account (GHCR already in use from Phase 2 Layer 1).
- OpenSSL ≥ 3.0 for the internal CA.
- Phase-3 RBAC enforcement is in place — Phase 4 OIDC layers identity over it without rewriting authorization.

## 3. Operational checklist

### Group A — Kubernetes runner

A1. **New host type** in [docs/yaml-schema.md](yaml-schema.md):
```yaml
hosts:
  k8s-prod:
    type: kubernetes
    kubeconfig_ref: vault://kube/prod
    context: production
    namespace: default
```

A2. **Architectural choice:** Kubernetes hosts have no daemon. CP instantiates an in-process Runner that talks to the K8s API. Choose between Python `kubernetes` client (in-process to CP, simpler) and a dedicated Go executor microservice (consistent with `maestrod` style). Document the choice in `phase-4-completion.md`.

A3. **`run.type: kubernetes` subforms:**
- `manifest_template`: Jinja2 template producing manifests; CP renders, applies (`kubectl apply` or API), waits for ready.
- `helm`: chart path or registry ref + values; `helm upgrade --install` via subprocess or SDK.

A4. **Healthcheck:** read `.status.readyReplicas` vs `spec.replicas`; for StatefulSet also ordering.

A5. **Rollback:** manifest reapply (previous version) or `helm rollback`.

A6. **Logs:** tail pods of the Deployment, aggregated.

A7. **Protocol:** the K8s Runner exposes the same orchestrator-facing interface as systemd / docker daemons. No WebSocket needed (in-process).

**Tests:**
- `test_k8s_runner_unit.py`: K8s client mock, manifest translation and state.
- `test_k8s_integration.py`: kind cluster, real nginx Deployment 1 replica, healthcheck, rollback.

### Group B — Postgres backend + Alembic

B1. **DAO abstraction:** every persistence path goes through a repository interface. Audit existing modules (already largely repository-shaped from CP v2) and remove any direct cursor uses.

B2. **PostgreSQL backend** alongside SQLite. Selection via `MAESTRO_DATABASE_URL` (`postgresql://...` or `sqlite:///...`).

B3. **Alembic** introduced now; first migration is the current baseline.

B4. **Migration script** `scripts/migrate-sqlite-to-postgres.py` copying all data + asserting referential integrity.

**Tests:**
- `test_db_backends.py`: same suite green against SQLite and Postgres (testcontainers).
- `test_migration.py`: dump → migrate → row-by-row equality check.

### Group C — High availability

C1. **Multi-instance CP behind LB.** Daemon ownership via consistent hashing on `daemon_id` → instance_id; on instance death, daemon reconnects and another instance picks up.

C2. **Leader election** via Postgres advisory lock (or `leader_lease` table). Only the leader runs the global git-sync poller, retention cleanup, lease expirations.

C3. **State sharing:** all persistent state in DB; nothing in local memory beyond caches.

C4. **`/healthz` readiness:** instance ready iff DB reachable + WS hub up + (if leader) lease renewed.

C5. **Graceful shutdown:** stop accepting new requests, instruct daemons to reconnect, finalize ongoing orchestrations or yield lease.

**Tests:**
- `test_ha_failover.py`: 2 instances + 1 daemon; kill the owner instance; daemon reconnects within 10 s; operations resume.
- `test_leader_election.py`: 2 instances; only one runs scheduled jobs; leader killed → other takes lease within 30 s.

### Group D — mTLS daemon ↔ CP

D1. **Internal CA:** `maestro ca init` (Phase 4 CLI subcommand) generates private CA + server cert. `maestro ca issue-daemon <host_id>` issues signed daemon keypair.

D2. **Distribution:** Phase-2 Layer-1 enrollment endpoint `POST /api/enroll/<token>/consume` is extended — response shifts from `{daemon_token}` to `{daemon_cert, daemon_key, ca_cert}`. Layer-2 enrollment design referenced in [docs/superpowers/specs/2026-04-22-installer-scripts-design.md](superpowers/specs/2026-04-22-installer-scripts-design.md). The same `curl …/enroll/<t> | sudo bash` flow is reused.

D3. **Rotation:** CP supports revocation (CRL in DB) and reissuance.

D4. **Backward compatibility:** TLS+token mode remains available, deprecated. Existing Phase-2 daemon installs keep working until reissued.

**Tests:**
- `test_mtls.py`: valid cert handshake; cert not signed by CA → rejected; revoked cert → rejected.

### Group E — OIDC / OAuth provider

E1. **OIDC backend** for human auth on UI/API: at least one working integration (Keycloak / Auth0 / Google — configurable). The Phase-3 RBAC role assignment is preserved — OIDC supplies identity, RBAC supplies authorization.

E2. **Static API tokens** for non-interactive integrations (MCP included; replaces / unifies the Phase-2 MCP API-key auth). Tokens bound to a role.

E3. **Auth provider interface** designed so additional providers are pluggable in v5+ without reshaping sessions.

**Tests:**
- `test_authn_oidc.py`: mocked OIDC provider, JWT validated, RBAC enforcement intact.
- `test_api_tokens.py`: token issuance + revocation + scoped to role.

### Group F — Maestro CLI

F1. **`maestro` binary** (Go for consistency with the daemon, or Python wheel — choose and document). Commands:
- `maestro config validate <file>`
- `maestro config apply <file>`
- `maestro deploy [--component X]`
- `maestro status [--deploy P]`
- `maestro logs <component> [--follow] [--lines N]`
- `maestro rollback <component> [--steps N]`
- `maestro tests run <component> [--type unit|integration|smoke|all]`
- `maestro vault {set,get,list,delete}`
- `maestro hosts list`
- `maestro ca {init,issue-daemon,revoke}` (D1).

F2. **Configuration** at `~/.config/maestro/config.yaml` (CP endpoint + token).

F3. **Output:** human-readable default, `--json` for structured.

**Tests:**
- `cli_test.go` (or `test_cli_unit.py`): argument parsing, request generation.
- `test_cli_e2e.py`: stack up + CLI flow equivalent to UI.

### Group G — Packaging and distribution

G1. **CI** (GitHub Actions): runs all tests; builds and publishes:
- `ghcr.io/<org>/maestro-control-plane:<version>` — already shipped in P2 Layer 1, this just folds into the release pipeline.
- `maestrod` binaries linux/{amd64,arm64} + darwin/{amd64,arm64} — already shipped in P2 Layer 1.
- **`.deb` and `.rpm`** packages for the daemon via `nfpm` or `goreleaser` — **new in P4**.

G2. **Helm chart** at `deploy/helm/maestro-control-plane/` to install CP on Kubernetes with optional Postgres sidecar or external connection.

G3. **`docker-compose.prod.yml`** template alternative to Helm.

G4. **`scripts/upgrade.sh`** orchestrates `install-cp.sh --upgrade` + `install-daemon.sh --upgrade` (already available from P2 Layer 1) across a fleet, with self-update of daemons via Phase-3 §F.1 where applicable.

### Group H — Documentation site

H1. **`docs/user/`:**
- `installation.md` (single-node, HA, K8s)
- `quickstart.md` (zero to first deploy in 10 minutes)
- `yaml-reference.md` (full schema)
- `mcp-reference.md` (every MCP verb)
- `api-reference.md` (generated OpenAPI + notes)
- `cli-reference.md`
- `troubleshooting.md` (every error code → remedy)
- `security.md` (RBAC + OIDC + mTLS setup + cert rotation)
- `observability.md` (metrics + tracing + audit)

H2. **Static site** generated with MkDocs (Material theme) or Docusaurus, published via CI on push to main, link-checked.

### Group I — OpenTelemetry tracing

I1. **OTLP export** configurable on CP and daemon.

I2. **Trace context propagation** through WebSocket envelopes via optional `trace_context` field.

I3. **Spans:** `config.validate`, `deploy.component`, `build`, `runner.start`, `healthcheck.wait`, `wizard.inspect`, `vault.resolve`, `gitsync.poll`.

I4. **Existing audit log** (Phase 3 §I) gets a `trace_id` field for correlation.

**Tests:** `test_tracing_propagation.py` — generated trace shows spans on CP and daemon (mocked collector).

### Group J — Skill hardening

J1. Update `skill/SKILL.md` with:
- Kubernetes section: K8s vs Linux targets reasoning.
- RBAC section: how the agent's role constrains available actions.
- mTLS section: how cert distribution works for non-admin enrollment.
- Cross-environment patterns (dev/staging/prod across multiple deploys per user).

## 4. Fixtures

- `tests/fixtures/deployment-k8s.yaml`
- `tests/fixtures/k8s-manifest-api.yaml.j2`
- `tests/fixtures/helm-chart-demo/`
- `tests/fixtures/oidc-mock-config.yaml`

## 5. Acceptance suite

1. **Phase 1/2/3 regression:** every prior acceptance flow passes.
2. **Kubernetes deploy:** kind cluster + `deployment-k8s.yaml` → Deployment created, pod ready, healthcheck OK, rollback OK, logs readable.
3. **Postgres parity:** stack with `MAESTRO_DATABASE_URL=postgresql://...` → all P1+P2+P3 acceptance flows pass.
4. **HA failover:** Group C tests demonstrated.
5. **mTLS:** Group D enforced; revoked cert rejected.
6. **OIDC + RBAC:** Phase-3 RBAC matrix re-run with OIDC-issued identities, results identical.
7. **CLI:** every command works; `--json` parseable; viewer-token CLI cannot deploy (403).
8. **Packaging:** CP image runnable with `docker run`; daemon installable from `.deb` on Ubuntu 22.04 and from `.rpm` on Rocky 9; Helm chart installable on kind.
9. **Docs:** site builds clean, link checker green, every error code has a `troubleshooting.md` entry.
10. **Performance:** idempotent deploy of 20 components across 3 hosts ≤ 3 min; CP sustains 50 daemons connected with footprint < 512 MB; `get_state` of 20-component deploy ≤ 200 ms.
11. **Tracing:** sample deploy generates a complete trace through the mocked collector, including audit-log correlation.
12. **Token efficiency benchmark (agents):** average tokens for typical agent workflow ("update API to commit X, verify healthcheck, rollback on failure") documented, target ≤ 30% of "free shell" baseline (comparative).

## 6. Out of scope (Phase 4)

- Multi-region / federated installations.
- Additional runners beyond systemd / docker / kubernetes.
- Alerting rules (deferred from CP v2 §6).
- Deploy sharing / co-ownership (deferred from CP v2 §6).
- Mobile-first UX (CP v2 §6).

## 7. Documents to produce at the end

- `docs/phase-4-completion.md` — deviations, architectural choices (K8s in-process vs microservice, CLI language).
- `README.md` updated with CI badges, docs link, quickstart link.
- `CHANGELOG.md` covering every release during the phase.

## 8. Quality criteria

- Test coverage ≥ 85% Python, ≥ 80% Go.
- Zero linter warnings in CI.
- Zero High/Critical CVEs (trivy or equivalent on the final image).
- Clean spell check on `docs/user/`.
- Every public API in OpenAPI; every MCP tool with documented input/output schema.
