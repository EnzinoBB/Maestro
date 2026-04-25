# Control Plane v2 — Vision Design

**Status:** draft
**Date:** 2026-04-24
**Scope:** architectural umbrella. Each numbered milestone (M1–M5) gets its own implementation spec in follow-up sessions.

## 1. Context & Motivation

The current Control Plane ([control-plane/app](../../control-plane/app)) is a FastAPI application with:
- An HTMX-based dashboard with dark-mode styling, live-polled via HTMX (`/ui/hosts`, `/ui/state-table`, `/ui/history`).
- A single-row `config` table storing **one** applied YAML per installation.
- A linear `deploy_history` table recording apply attempts.
- No collected metrics: the `T_EV_METRICS` protocol event is declared in [app/ws/protocol.py](../../control-plane/app/ws/protocol.py) but never emitted or consumed.
- Single-user, no authentication, no ownership model.
- An MCP stdio server ([app/mcp/server.py](../../control-plane/app/mcp/server.py)) delegating to the REST API.

This works for the Phase-1 acceptance tests against the two target hosts (host1, host2), but falls short of a usable first-class product for human operators. The gaps are:

1. **One deploy at a time** — no way to manage "webapp-prod" and "monitoring-stack" as independent units.
2. **No observability** — operators cannot tell how a component behaves between apply events.
3. **Manual YAML authoring** — every deploy requires hand-written YAML.
4. **Barebones UI** — tables and form, no drill-down, no graphs, no guidance.
5. **No multi-user story** — the CP cannot be operated by multiple humans or provided as a service.

This document defines the target shape of the Control Plane across five coordinated subsystems. It is the umbrella spec; each milestone M1–M5 will have its own implementation spec.

## 2. Guiding Principles

- **Primitives over special cases.** New verbs must be generalizable. Docker wizard is a *source-type specialization* of a polymorphic primitive, not a feature of its own. (See memory: "Generalizzare le primitive, non special-case".)
- **Isolation between subsystems.** Each milestone must ship independently, with its own integration tests, and without blocking the others.
- **Forward-compatible storage.** SQLite today; every data-access path goes through a repository interface that can be swapped for a TSDB or external RDBMS later without touching callers.
- **API-first.** The SPA, MCP, and any future CLI all consume the same REST + WS surface.
- **Single-user must keep working.** The multi-user layer activates opt-in; the default installation remains single-user with zero auth friction.

## 3. Subsystem Architecture

### §1. Multi-Deploy Data Model (M1)

**Goal:** turn "deploy" into a first-class named entity with per-deploy version history, replacing the current single-row `config` table.

**Entity model:**

```
deploys
  id               TEXT PK
  name             TEXT           -- unique per owner_user_id
  owner_user_id    TEXT FK users NOT NULL  -- always set; in single-user mode, points to the materialized 'singleuser' admin row
  current_version  INTEGER        -- points into deploy_versions
  state_summary    TEXT JSON      -- cached aggregate (components_total, healthy, last_apply_ts)
  created_at       REAL
  updated_at       REAL

deploy_versions
  id                 TEXT PK
  deploy_id          TEXT FK deploys
  version_n          INTEGER      -- monotonic per deploy
  yaml_text          TEXT
  components_hash    TEXT         -- stable hash over normalized component set (incl. config_archives)
  parent_version_id  TEXT FK deploy_versions  -- the version this one was derived from (NULL for first)
  applied_at         REAL
  applied_by_user_id TEXT FK users
  result_json        TEXT         -- engine.apply result envelope
```

**Rollback semantics.** A rollback to version M is implemented as: read `deploy_versions[M].yaml_text` → auto-snapshot current as `version_n+1` with a distinguishing flag → apply M's YAML as `version_n+2`. The chain is never rewritten; rollbacks are forward-only operations that produce a new version whose `parent_version_id` points to M. This preserves an audit trail ("version 7 was a rollback to version 3").

**Shared-host conflict handling.** Because multiple deploys may target the same host, the validator gains two cross-deploy checks at apply time. "Current" here means: the YAML of the deploy's `current_version`, considering only components bound to the host in question via an active `DeploymentBinding`.
- **Component-id collision:** no two deploys may place components with the same `component_id` on the same host in their respective current versions.
- **Port collision:** listening ports declared in `run.ports` are checked against the ports claimed by components of other deploys on the same host in their current versions.

Conflicts surface as validation errors (not warnings) in the diff response, so the wizard and raw-editor flows both see them uniformly.

**API surface:**
```
GET    /api/deploys                       # list (filtered by owner + ACL)
POST   /api/deploys                       # create empty deploy
GET    /api/deploys/{id}                  # detail + current version
POST   /api/deploys/{id}/validate         # validate against current cluster state
POST   /api/deploys/{id}/diff             # diff proposed YAML vs current
POST   /api/deploys/{id}/apply            # apply proposed YAML (creates new version)
GET    /api/deploys/{id}/versions         # list versions
POST   /api/deploys/{id}/rollback/{vN}    # rollback to version N
DELETE /api/deploys/{id}                  # tear down (decommissions all components)
```

The existing `/api/config/*` endpoints remain for one release as thin shims over the default deploy, to keep Phase-1 tooling working during migration.

### §2. Telemetry (M2)

**Goal:** full-spectrum metrics collection pushed from daemons to the CP over the existing WS channel.

**Scope of measured data:**
- **Host-level** (every N=15s, configurable): CPU %, RAM used/available, disk usage per mount, network rx/tx bytes, 1/5/15 load average.
- **Per-component** (same cadence): process CPU %, RSS, restart count delta, uptime, last healthcheck result (ok/failed/unknown) + latency.
- **Log activity**: line rate per component (lines/sec over the last window), error-rate proxy (lines matching a configurable pattern).
- **Custom scrape**: if a component declares `metrics: { endpoint: /metrics, port: 9100 }`, the daemon scrapes it and relays a subset of named metrics (allow-list configured per component, to cap bandwidth).
- **Deploy-level** (derived CP-side): `components_total`, `components_healthy`, `last_apply_duration_ms`, `success_rate_7d`.

**Transport.** Daemon emits `T_EV_METRICS` envelopes every N seconds over the existing `/ws/daemon` connection. The event payload carries a batch of samples keyed by `(scope, scope_id, metric_name)`. CP persists via `MetricsRepository`.

**Storage (v2):** SQLite with rolling retention.
- Raw samples at native resolution: retained 24h.
- Downsampled to 1-minute mean: retained 30 days.
- Events (apply, rollback, restart, healthcheck state change): retained indefinitely, bounded by row count cap per deploy (e.g. 10k).

```
metric_samples
  ts             REAL
  scope          TEXT         -- 'host' | 'component' | 'deploy'
  scope_id       TEXT         -- host_id, component_id, deploy_id
  metric_name    TEXT
  value          REAL
  -- indexed on (scope, scope_id, metric_name, ts)

metric_events
  ts             REAL
  kind           TEXT         -- 'apply_started' | 'apply_completed' | 'healthcheck_state_change' | ...
  scope          TEXT
  scope_id       TEXT
  payload_json   TEXT
```

**API surface:**
```
GET  /api/metrics/host/{host_id}?from&to&step&metrics=cpu,ram,...
GET  /api/metrics/component/{component_id}?...
GET  /api/metrics/deploy/{deploy_id}?...
GET  /api/events?scope=deploy&scope_id=X&kind=apply_*
```

All return time-series arrays suitable for direct consumption by Recharts on the client.

**Evolution path.** `MetricsRepository` is the seam. If the rolling-window SQLite approach saturates (tentative threshold: > 5 nodes × 10 components × 15s sampling sustained for days), we swap the implementation for a TSDB (likely VictoriaMetrics standalone) without touching API handlers.

### §3. Deploy Wizard (M3)

**Goal:** guided deploy authoring that produces a draft YAML reviewed via diff before apply.

**Polymorphic skeleton.** Every wizard run picks a `source_type` on step 1 (`docker | git | archive`). The skeleton is:
1. Entry point & target deploy (new / add-to-existing / upgrade-component-of-existing).
2. Source selection.
3. Source-specific enrichment (see below).
4. Placement: pick host(s), strategy (sequential/parallel/canary), depends-on.
5. Runtime config: env, volumes, ports, secrets refs, healthcheck.
6. Review: generated YAML + diff against the target deploy's current version.
7. Apply (or save as draft without applying).

**Source-specific enrichment:**
- **Docker:** backend runs `docker manifest inspect` (or a pull + inspect on a sandboxed host) to extract declared `ExposedPorts`, `Volumes`, `Env` → pre-fills steps 4–5 with suggestions the user can edit.
- **Git:** step asks for repo URL + ref + build steps template (dropdown of common patterns: Dockerfile / npm / pip / go build).
- **Archive:** user uploads; backend records artifact hash; run config is manual.

**Entry-point variants:**
- **New deploy:** creates a `deploys` row + initial `deploy_versions` with the wizard's YAML.
- **Add component:** target is an existing deploy; wizard loads current YAML, inserts the new component block, produces diff.
- **Upgrade component:** target is a specific `(deploy, component_id)`; wizard shows current source ref → asks for new ref (e.g. image tag bump) → diff-only change.

**Output contract.** Every wizard path produces the same artifact: a proposed YAML + a diff response. Wizard and raw-editor flows are indistinguishable to the apply engine. This is the "primitive not special case" principle applied to the wizard itself.

**Power-user escape hatch.** Raw YAML editor (today's `/ui/load-current` + textarea) remains available on the deploy-detail page; wizard is an alternative UI over the same apply primitive.

### §4. Frontend SPA + Realtime (M4)

**Stack:** React 18 + Vite + Tailwind + shadcn/ui + TanStack Query + Recharts. Chosen for:
- Direct compatibility with Claude Design output (React/Tailwind/shadcn).
- First-class real-time rendering of time-series (Recharts + WS subscription).
- Mature wizard-form ecosystem (react-hook-form + zod for schema validation).

**Packaging.** A `web-ui/` directory at the repo root contains the Vite project. CI builds to `web-ui/dist/`; FastAPI mounts it at `/` via existing `StaticFiles`. Dev mode: Vite dev server at `:5173` proxies `/api` and `/ws` to FastAPI at `:8000`.

**API client.** One typed client generated from FastAPI's OpenAPI schema via `openapi-typescript-codegen` at build time. TanStack Query handles cache, retries, optimistic updates.

**Real-time channel: `/ws/ui`.** A second WebSocket on the CP, distinct from `/ws/daemon`. The CP broadcasts to subscribed browser clients:
- New metric samples (batched per-second).
- Component/deploy state changes.
- Apply progress events (per-host, per-component).

Client-side, a single `useRealtimeChannel(topic)` hook wraps subscription + reconnection.

**Information Architecture:**

| Section | Purpose | Source data |
|---|---|---|
| Overview | Grid of user's deploys, each card with health summary + last-apply status. Global indicators (total components healthy / total, active alerts). | `/api/deploys` + `/api/metrics/deploy/*` |
| Deploy detail | Component list with per-component live metrics sparklines; version history with rollback button; quick actions (apply, wizard entry, raw editor). | `/api/deploys/{id}` + `/api/metrics/component/*` + `/ws/ui` |
| Nodes | List combining `user` + accessible `shared` nodes, with host metrics preview. Detail page: full host metrics + components running on this host across all accessible deploys. | `/api/nodes` + `/api/metrics/host/*` |
| Wizard | Multi-step flows for new-deploy / add-component / upgrade-component. | `/api/deploys/{id}/diff` + `/api/deploys/{id}/apply` |
| Admin | Visible only to users with `is_admin=1` or org-admin role. Manage users, orgs, shared nodes, access grants. | `/api/admin/*` |

**Responsive:** desktop-first. Tablet/mobile degraded-but-usable (read-only on mobile is acceptable for v2).

### §5. Auth & Multi-Tenant (M5)

**Goal:** opt-in multi-user with per-user resource isolation, organization-provided shared nodes, and explicit ACL sharing.

**Entity model:**

```
users
  id             TEXT PK
  username       TEXT UNIQUE
  email          TEXT UNIQUE NULL
  password_hash  TEXT
  is_admin       INTEGER      -- platform-level admin
  created_at     REAL

organizations
  id             TEXT PK
  name           TEXT UNIQUE
  created_at     REAL

org_members
  org_id         TEXT FK organizations
  user_id        TEXT FK users
  role           TEXT         -- 'admin' | 'member'
  PRIMARY KEY (org_id, user_id)

nodes
  id             TEXT PK
  host_id        TEXT UNIQUE  -- matches the daemon-side host_id
  node_type      TEXT         -- 'user' | 'shared'
  owner_user_id  TEXT FK users NULL  -- set when node_type='user'
  owner_org_id   TEXT FK organizations NULL  -- set when node_type='shared'
  created_at     REAL

node_access
  node_id        TEXT FK nodes
  user_id        TEXT FK users
  role           TEXT         -- 'viewer' | 'operator' | 'admin'
  PRIMARY KEY (node_id, user_id)
```

`deploys.owner_user_id` is always NOT NULL; in single-user mode it points to the materialized `singleuser` row (created at install with `is_admin=1`).

**Visibility rules (checked by middleware):**
- **Node visibility** (user `U`): `nodes.owner_user_id = U` OR `node_access[node, U]` exists. For `shared` nodes, visibility is entirely driven by `node_access` (populated by the org's admins).
- **Deploy visibility**: only `owner_user_id = U`. (No deploy sharing in v2; reconsider in v3.)
- **Component placement at apply time**: every `host` referenced by the deploy must resolve to a node visible to the owner. Otherwise validation fails with a clear message.

**Auth mechanism:**
- Local password authentication (bcrypt, cost factor 12).
- Session as JWT cookie: `HttpOnly`, `Secure`, `SameSite=Lax`, 7-day sliding expiry.
- CSRF: double-submit cookie pattern for mutating endpoints.
- OAuth (GitHub/Google) is explicitly deferred to v3; the auth backend is an interface so we can add providers without reshaping sessions.

**Single-user mode:** controlled by `MAESTRO_SINGLE_USER_MODE` env var.
- **Default ON** on a fresh install. The installer materializes a `singleuser` row in `users` with `is_admin=1` and no usable password. No login page is shown; API calls resolve to this user via a stub middleware. All nodes and deploys are owned by `singleuser`.
- Admin enables multi-user mode by running a setup command (`maestrod setup-admin`) that:
  1. Creates the first real user with an interactively-chosen password.
  2. Reassigns all existing resources to that user.
  3. Flips the flag in DB config (`MAESTRO_SINGLE_USER_MODE` env still honored as an override).
- Once multi-user is active, further users are created through the admin UI.

**Daemon auth stays orthogonal.** Daemons authenticate with `MAESTRO_DAEMON_TOKEN` as today. Human auth and daemon auth never cross.

## 4. Cross-Subsystem Concerns

### Data access pattern

Every subsystem introduces or touches a repository class in [control-plane/app/storage.py](../../control-plane/app/storage.py) or a new sibling module. Handlers depend on the repository interface, never on SQL directly. This preserves the swap path for TSDB (M2) and for moving to Postgres in the future.

### Websocket broadcasting

Two distinct WS surfaces:
- `/ws/daemon` (existing): daemon ↔ CP, request/response envelopes.
- `/ws/ui` (new, M4): CP → browser, fanout.

A shared `EventBus` (in-process pub/sub) decouples producers (engine apply events, metrics ingestion) from consumers (`/ws/ui` broadcasters, metric persisters). This keeps the engine testable without a running WS server.

### Migration / backwards compatibility

- **Data migration (M1):** a one-time script reads the existing single `config` row and creates a `default` deploy owned by `singleuser`. Old `/api/config/*` endpoints remain as shims targeting this default deploy, deprecated but working for two minor versions.
- **Daemon compatibility:** daemons running current firmware keep working through M1–M3. M2 introduces opt-in metrics emission; daemons without it show "metrics unavailable" in the UI rather than error.
- **MCP tools:** the existing tools ([app/mcp/server.py](../../control-plane/app/mcp/server.py)) stay backward-compatible by operating on the default deploy when no `deploy_id` is passed. New deploy-aware tools are added alongside.

### Testing strategy

- **M1:** integration tests against real SQLite, asserting version-chain invariants (monotonic version_n per deploy, parent_version_id consistency).
- **M2:** unit tests with fake clock; integration test: a daemon emits canned `T_EV_METRICS`, CP persists, API returns correct time-series.
- **M3:** golden YAML files. Wizard state + inputs → expected generated YAML. One golden per source-type × entry-point.
- **M4:** Playwright end-to-end against a seeded CP (single-user mode, default deploy, fake metrics).
- **M5:** visibility matrix test — 3 users, 2 orgs, 4 nodes of mixed types; enumerate every (user, resource) pair and assert the expected access verdict.

## 5. Sequencing

Milestones ship in order; each is independently testable and deliverable.

| # | Milestone | Ships | Prerequisite |
|---|---|---|---|
| M1 | Multi-deploy data model | `deploys`/`deploy_versions` schema, API, migration | — |
| M2 | Telemetry | Metrics push, storage, API, events | M1 (deploy-level metrics) |
| M3 | Wizard backend | Polymorphic generator, docker enrichment, API | M1 |
| M4 | Frontend SPA | React app, `/ws/ui`, feature-parity with current HTMX | M1, M2, M3 |
| M5 | Auth & multi-tenant | users/orgs/ACL schema, single-user flag, middleware | M1 (owner column), M4 (login UI) |

Each milestone gets its own implementation spec — this document does not prescribe implementation detail beyond the architectural boundaries above.

## 6. Out of Scope (v2)

Items explicitly NOT addressed here, for future consideration:
- **Deploy sharing between users** (co-ownership / handoff). Model is "owned by one user"; reconsider in v3.
- **OAuth / SSO / SAML.** Local password only in v2.
- **Secrets management.** Secrets are still referenced by `credentials_ref` as today; a first-class secrets store is v3+.
- **Dedicated TSDB.** SQLite rolling window until it hurts.
- **Autoscaling / scheduling** (beyond explicit host placement in the spec).
- **Alerting rules.** Metrics are visualized in v2; alert thresholds and notification channels are v3.
- **Mobile-first UX.** Desktop-first is explicit; mobile is best-effort read.

## 7. Open Questions

These are not blockers for the vision doc but will need resolution during M1–M5 specs:

- **Retention of soft-deleted deploys.** When `DELETE /api/deploys/{id}` is called, do we hard-delete or soft-delete (allowing restore)? Leans toward soft-delete with a TTL.
- **Component-hash stability across daemon versions.** Hash is used to detect "no-op" applies. Needs a normalization layer shared between CP and daemon.
- **`/ws/ui` authentication in multi-user mode.** Probably the JWT cookie passed on upgrade, but CSRF implications differ for long-lived WS connections — needs M5-level design.
- **Docker manifest inspection without pulling.** `docker manifest inspect` exists but is registry-dependent; fallback to `docker pull && docker inspect` on a designated "builder" daemon may be needed for private registries.
