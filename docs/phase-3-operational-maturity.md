# Phase 3 — Operational Maturity

> **Status:** active.
> **Predecessor:** [phase-2-completion.md](phase-2-completion.md).
> **Successor:** [phase-4-production-scale.md](phase-4-production-scale.md).
> **Goal:** turn the Phase-2 multi-deploy / multi-tenant CP into something operationally complete on a single instance — so a daily operator never has to drop to shell or hand-edit YAML to recover from failure.

## 1. Scope

Phase 3 fills the operational gaps left by the CP v2 pivot. Concretely: zero-downtime deployment modes, automatic rollback, a real test framework, secrets management, git-driven CI/CD, granular lifecycle primitives, MCP completeness, RBAC enforcement, audit logging, and basic hardening. **No infrastructural changes** — single-instance SQLite is preserved (Phase 4 covers K8s, Postgres, HA, mTLS, OIDC).

## 2. Prerequisites

- Repository at the state of [phase-2-completion.md](phase-2-completion.md).
- The schema in `control-plane/app/config/schema.py` already accepts `deploy_mode: hot|blue_green|cold`, `strategy: canary`, and `credentials_ref` — these are scaffolding the implementations attach to.
- The `app/credentials/` directory exists empty (placeholder) and must be filled.
- Phase 1 + Phase 2 acceptance flows must continue to pass at the start and at the end.

## 3. Operational checklist

### Group A — Hot deploy / blue-green / canary

The schema already accepts `deploy_mode` and `strategy: canary`. The motor is missing on both sides.

A1. **Daemon — `deploy_mode: hot`:**
- Docker: start a new container with a temporary name, wait for positive healthcheck, atomic name swap, remove old container. Tolerate ≤ 2 errors per 100 requests on continuous `curl` against published ports.
- Systemd: `systemctl reload` if the unit defines `ExecReload`; otherwise side-by-side install + `daemon-reload` + `restart` minimizing downtime.

A2. **Daemon — `deploy_mode: blue_green`:** keep two permanent installations (`-blue` / `-green` suffix on container_name / unit_name), expose declared ports through the active one, switch on apply.

A3. **Orchestrator — `strategy: canary`:**
- Single-host: virtual ≥ 1 instance group; multi-host: applies to the host group.
- Deploy `initial_fraction` → wait `verify_duration` + healthcheck → expand by `step_fraction` until 100%, or roll back on verification failure.

A4. **`reload_triggers` field (new in schema):** when a deploy diff changes only the configuration of a `hot` component (not its source), perform a reload instead of a restart.

**Tests:**
- `test_hot_deploy_docker_test.go` (daemon): nginx hot deploy with continuous `curl` every 100 ms during swap → no 5xx (≤ 2/100 tolerated).
- `test_canary_orchestrator.py` (CP): two simulated hosts, gradual rollout and rollback on failure.
- `test_blue_green_test.go` (daemon): blue-green swap preserves the unselected installation as a fallback.

### Group B — Automatic rollback

B1. **Healthcheck-driven rollback:** on N consecutive failed post-deploy healthchecks, the orchestrator issues `request.rollback` for the offending component. If the strategy was multi-component (a session), it also rolls back components deployed earlier in the same session.

B2. **Test-driven rollback:** on a failed `blocking: true` post-deploy test (Group C), same flow.

B3. **Rollback envelope (new daemon protocol):** `request.rollback` carries `{component_id, steps_back: 1}` or `{component_id, to_hash: "..."}`. Daemon keeps the last N=5 hashes per component plus the artifacts needed to revert (tagged docker image, tarball of previous code, previous config) — the existing 10-hash history in state already supports this.

B4. **API + UI:** `POST /api/components/{id}/rollback?steps=1` (single-component, distinct from M1's `POST /api/deploys/{id}/rollback/{vN}` which restores a whole deploy version). UI: per-component "Rollback" with steps selector.

**Tests:**
- `test_rollback_daemon_test.go`: deploy A → deploy B → rollback → state identical to A.
- `test_auto_rollback.py`: deploy with deliberately failing healthcheck → automatic rollback within timeout.

### Group C — Component test framework

C1. **Schema:** add `tests` field to `ComponentSpec`:
```yaml
tests:
  unit:
    command: npm test
    when: pre_deploy
    blocking: true
  integration:
    command: npm run test:integration
    when: post_deploy
    requires: [db, redis]
  smoke:
    http: GET /health
    expect: 200
    when: post_deploy
```

C2. **Daemon — `request.tests.run`:** payload selects `unit | integration | smoke | all`. Handler:
- `command` tests: run in working_dir, capture stdout/stderr tails, structured response `{name, ok, duration_ms, stdout_tail, stderr_tail, exit_code}`.
- `http` tests: make request, verify status / body shape.
- `requires:` (post-deploy only): verify listed components running before executing.

C3. **Orchestrator integration:** pre-deploy `blocking: true` failure → cancel with structured error. Post-deploy `blocking: true` failure → trigger Group B rollback. Results persisted as new `metric_events` of `kind='test_run'`.

C4. **UI:** "Tests" tab on component detail with history of results.

**Tests:**
- `test_tests_runner_daemon_test.go`: command success/failure, output capture, timeout.
- `test_orchestrator_with_tests.py`: blocking pre fail → cancel; blocking post fail → rollback called.

### Group D — Credential vault

D1. **Backend:** `control-plane/app/credentials/file_backend.py` — encrypted file vault. Master key derived via scrypt (N=2^15, r=8, p=1) from operator passphrase. Format: version header + salt + AES-256-GCM over JSON payload. Interface `Vault` with `get(ref) / put / delete / list`.

D2. **CLI helper:** `python -m app.credentials.cli` (or `scripts/vault.py`) with `init / set <path> <value> / get <path> / list`.

D3. **Orchestrator integration:** when a deploy payload references `{{ vault://... }}` (or the structured `credentials_ref` field already in schema), secrets are resolved JIT before being shipped to the daemon in the `secrets` section of `request.deploy`. **Never written to disk in cleartext.**

D4. **Git credentials:** same vault, conventional path `git.<alias>`. CP's git clone uses resolved credentials.

D5. **Master key delivery:** passphrase loaded once at CP startup from `MAESTRO_VAULT_PASSPHRASE` env (no UI prompt in v3 — that is Phase 4 OIDC territory).

**Tests:**
- `test_credentials.py`: init + set + get + list + delete; wrong passphrase → clear error; corrupted file → error code; templated reference resolved correctly.
- Cleartext check (combined with §J4): log scanner verifies zero known-pattern leakage after a full deploy with a vault-referenced secret.

### Group E — Git-sync auto-deploy

E1. **Module `control-plane/app/gitsync/`:**
- `poller.py`: periodic polling of tracked refs for all `source.type: git` components; default 5 min, configurable per component.
- `webhook.py`: `POST /api/webhooks/{provider}` for GitHub / GitLab / Gitea / Bitbucket payloads, signature-verified.
- `sync.py`: on new commit, set "drift detected" state for the component; consult policy (`auto_deploy: true|false`, default false); if auto, trigger deploy via the M1 engine creating a new deploy version.

E2. **Storage:** new `git_tracked_refs` table `(component_id, branch, last_seen_commit, updated_at)`.

E3. **YAML extension:**
```yaml
components:
  api:
    source:
      type: git
      repo: ...
      ref: main
      sync:
        poll_interval: 5m
        auto_deploy: true
```

E4. **UI:** "drift detected" badge on component cards; "Deploy latest" inline action.

**Tests:**
- `test_gitsync_poller.py`: mocked repo new-commit detection.
- `test_webhook.py`: signed and unsigned GitHub payloads.
- `test_git_autodeploy.py` (e2e): local bare repo → push → component redeployed within 30 s.

### Group F — Granular lifecycle primitives

#### F.1 — Artifact upload + `source.type: artifact`

- **REST:** `POST /api/artifacts` (multipart or JSON+`content_b64`) → `{artifact_id, sha256, size, created_at}`. `GET /api/artifacts`, `GET /api/artifacts/{id}`, `DELETE /api/artifacts/{id}`. Local storage with sha256 dedup, configurable TTL (default 24 h), metadata in DB.
- **Schema:** `source.type: artifact` with `artifact_id`. Orchestrator embeds bytes in `request.deploy` payload (reuses `inline_tarball` envelope subtype, or new `binary_executable` for single executables).
- **MCP:** `upload_artifact(path|bytes, name?)` → `{artifact_id}`; `update_component(component_id, source?)` for in-place component update without canonical YAML mutation.
- **Daemon self-update** as a special case: declare the daemon as a managed component with `self_update: true`. Daemon writes new binary to `/usr/local/bin/maestrod.new`, spawns child on alternate health endpoint, performs atomic binary swap + `systemctl restart maestro-daemon`. Safety: new process must reconnect to CP within 60 s default, otherwise auto-revert previous binary.

#### F.2 — Component removal + `prune`

- **Daemon `request.component.remove`** payload `{component_id, keep_volumes?, keep_state?}`. Docker: `docker rm -f` + remove declared volumes (skip if `keep_volumes`). Systemd: `systemctl stop+disable` + remove unit + remove `/opt/maestro/<id>/`. Delete state row (unless `keep_state`). Emit `event.component_removed`.
- **Orchestrator:** implement the `to_remove` branch of the diff (currently skipped). `apply_config?prune=true` actually performs removals; default `prune=false` preserves Phase-2 behavior.
- **MCP:** `remove_component(component_id, keep_volumes?)`.

#### F.3 — Host diagnostics

- **Daemon `request.host.diagnostics`** returns aggregated snapshot:
```json
{
  "host_id": "host1",
  "os": {"name": "Ubuntu", "version": "24.04", "kernel": "..."},
  "uptime_sec": 86400,
  "cpu": {"count": 4, "load_1m": 0.4, "load_5m": 0.3},
  "memory_mb": {"total": 8192, "used": 2048, "available": 6144},
  "disk": [{"path": "/", "total_gb": 100, "used_gb": 43}],
  "runtimes": {"docker": {"active": true, "version": "29.1.3"},
               "systemd": {"active": true, "version": "255"}},
  "daemon": {"version": "0.2.0", "uptime_sec": 3600, "reconnects": 0}
}
```
- **MCP:** `get_host_diagnostics(host_id)`.
- Token target: ≤ 2 KB per host with ≤ 5 components.

**Tests (covering all three sub-groups):**
- `test_artifact_upload.py`: upload + sha256 dedup + TTL + delete.
- `test_artifact_deploy_test.go`: e2e tarball deploy via artifact.
- `test_self_update.py`: build maestrod 0.2.0-test, upload, deploy as self-update, verify version bump after reconnect, downtime ≤ 10 s; fault injection: new binary fails to reconnect within 60 s → automatic revert.
- `test_remove_daemon_test.go`: deploy → remove → container/unit gone, `keep_volumes` honored.
- `test_orchestrator_prune.py`: `prune=true` removes components no longer in YAML, `prune=false` leaves them.
- `test_diagnostics_daemon_test.go`: mocked system commands, output structure.
- `test_mcp_diagnostics.py`: round-trip ≤ 2 KB per host.

### Group G — MCP completeness

Add the missing verbs to `control-plane/app/mcp/tools.py`:

- `rollback(component_id, steps?)` and `rollback_deploy(deploy_id, version_n)`
- `run_tests(component_id, type)`
- `get_deployment_history(deploy_id?, limit=20)`
- `get_metrics(scope, scope_id, from?, to?, step?, metrics?)`
- `tail_logs_stream(component_id)` if MCP SDK supports streaming, else stays request/response and is documented as such
- `drift_status(deploy_id?)`
- `upload_artifact(path|bytes, name?)`
- `update_component(component_id, source?)`
- `remove_component(component_id, keep_volumes?)`
- `get_host_diagnostics(host_id)`

Update `skill/SKILL.md` with: mental model, standard flow (validate → diff → confirm → apply → watch → verify → rollback if needed), error taxonomy + suggested actions, YAML conventions and anti-patterns, token-efficient log/metric reading patterns, example dialogs.

**Tests:**
- `test_mcp_tools_v3.py`: every tool with valid + invalid input; output structure validated.
- `test_skill_coverage.py`: grep `SKILL.md` against the tool list — every tool documented.

### Group H — RBAC granular enforcement

The M5.5 schema (organizations, org_members, nodes, node_access) and the M5.5 admin UI exist, but per-action authorization enforcement is partial (`require_user` middleware only). Phase 3 closes this.

H1. **Predefined roles:** `admin` (platform), `org_admin`, `operator`, `viewer`.

H2. **Per-resource permissions:** `deploy.read | deploy.write | deploy.apply | deploy.rollback`, `component.deploy | component.rollback | component.remove`, `vault.read | vault.write`, `artifact.upload | artifact.delete`, `node.read | node.share`, `audit.read`, `host.create | host.revoke`.

H3. **Enforcement:** every mutating REST endpoint and every MCP tool checks the caller's permission set against the target resource. Failures return `403` with `code=permission_denied` + `required_permission`.

H4. **UI:** disable / hide controls the user is not authorized for. Non-blocking: server is the source of truth.

**Tests:** `test_rbac.py` — viewer cannot deploy, operator cannot manage vault, admin can do everything; 4 roles × ~12 actions matrix.

### Group I — Audit log

I1. **JSONL rotated file** `audit.log` with fields:
```
ts, request_id, actor_type (user|agent|system), actor_id,
action, target_type, target_id, result (ok|error), error_code?
```

I2. **Coverage:** all mutating API endpoints, all MCP tool calls, all enrollment lifecycle events, daemon-emitted lifecycle events relayed by the CP.

I3. **API:** `GET /api/audit?actor=&action=&target=&from=&to=&limit=` (admin-only or `audit.read` permission).

I4. **UI:** Admin → Audit page with filters.

**Tests:** `test_audit_log.py` — every covered action produces a record with the expected fields.

### Group J — Hardening

J1. **HTTP security headers** on UI responses: CSP (script-src self only — Vite bundle), HSTS, X-Content-Type-Options, X-Frame-Options.

J2. **Rate limiting** on `POST /api/auth/login`, `POST /api/auth/setup-admin`, `POST /api/webhooks/*`, and `POST /api/enroll/*` (sliding window per remote IP).

J3. **Logger allow-list:** the structured logger drops fields not in an explicit allow-list when the record passes through environments tagged `secrets-sensitive` (deploy payloads, vault operations).

J4. **Secret-leak regression test** (combined with D5): scan logs after a full vault-referenced deploy; zero matches against a known-pattern panel.

### Group K — Backup script

K1. **`scripts/backup.sh`:** snapshots `control-plane/data/` (SQLite + vault file + audit log) into a timestamped tarball, with optional `--remote` to push via scp to a backup host.

K2. **`scripts/restore.sh`:** reverse, with a safety gate ("control plane must be stopped") and idempotency.

**Tests:** `test_backup_restore.sh` — backup → wipe → restore → CP comes up with same `/api/deploys` and `/api/audit` content.

## 4. Acceptance suite

1. **Phase 1 + Phase 2 regression:** all prior acceptance flows continue to pass.
2. **Vault:** init + `vault set db/password "secret"` + deploy with `{{ vault://db/password }}` → component receives correct env; restart with wrong passphrase → clear error, no crash.
3. **Git-sync:** `auto_deploy: true` + push → redeploy within poll interval (or immediately on webhook); audit log records the event.
4. **Test framework:** blocking pre-test failure → deploy cancelled. Blocking post-test failure → automatic rollback completed.
5. **Hot deploy:** nginx hot deploy with continuous `curl` loop → ≤ 2 errors / 100 requests.
6. **Canary:** 3 simulated hosts with `initial_fraction: 0.34` → progresses 1/3 → 2/3 → 3/3; failure mid-rollout → already-deployed hosts roll back.
7. **MCP completeness:** Python script exercises every documented verb; structure validated.
8. **Token efficiency:** `get_deployment_history` honors `limit` (default 20); errors always carry `code` + `message` + (when applicable) `suggested_fix`; deploy payload to daemon ≤ 4 MB or fails with a clear "use git source instead" error.
9. **Artifact + self-update:** upload → `update_component` redeploys only the targeted component; TTL eviction returns clear `not_found`; daemon self-update from 0.1.0 → 0.2.0-test with disconnection ≤ 10 s; fault-injected new binary not reconnecting → revert to 0.1.0.
10. **Removal:** `remove_component` → container/unit gone, state row removed. YAML edit + `apply_config?prune=true` → component removed; `prune=false` → component preserved (Phase 2 backcompat).
11. **Diagnostics:** `get_host_diagnostics` for both hosts → complete payload, ≤ 2 KB per host, latency ≤ 500 ms.
12. **RBAC matrix:** scripted permission table — every (role, action) returns expected verdict.
13. **Audit:** every mutating action of acceptance flows 2-12 produces an audit record.
14. **Backup/restore:** roundtrip preserves CP state.

## 5. Out of scope (Phase 3)

- Kubernetes runner — Phase 4 §A.
- PostgreSQL backend — Phase 4 §B.
- HA / leader election — Phase 4 §C.
- mTLS — Phase 4 §D.
- OIDC / OAuth providers — Phase 4 §E.
- `maestro` CLI binary — Phase 4 §F.
- `.deb` / `.rpm` / Helm chart — Phase 4 §G.
- Documentation site — Phase 4 §H.
- OpenTelemetry tracing — Phase 4 §I.
- Deploy sharing across users — explicitly deferred per CP v2 vision §6.
- Alerting rules — explicitly deferred per CP v2 vision §6.

## 6. Quality criteria

- Test coverage ≥ 85% Python, ≥ 75% Go.
- Rollback ≤ 15 s per Docker component.
- Daemon reconnect ≤ 10 s.
- Self-update downtime ≤ 10 s.
- Zero secrets in cleartext on disk (D5 + J4 verify).
- Audit log completeness: 100% of mutating actions covered (I tests verify).

## 7. Documents to produce at the end

- `docs/phase-3-completion.md` — summary, deviations, operational notes.
- Update `docs/yaml-schema.md` — `tests`, `reload_triggers`, `source.type: artifact`, `self_update`.
- Update `docs/protocol.md` — `request.tests.run`, `request.rollback`, `request.component.remove`, `request.host.diagnostics`.
- Update `skill/SKILL.md` — see Group G.
- Update `README.md` with Phase 3 features.
