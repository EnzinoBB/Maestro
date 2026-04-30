# Phase 2 — Completion Report

> **Status:** closed.
> **Predecessor:** [phase-1-completion.md](phase-1-completion.md).
> **Active successor:** [phase-3-operational-maturity.md](phase-3-operational-maturity.md).

## 1. What Phase 2 actually became

The original Phase 2 plan (`phase-2-beta.md`, now removed) prescribed nine work groups: schema v2, vault, git-sync, test framework, hot/blue-green/canary, automatic rollback, full MCP, rich UI, packaging — plus three lifecycle primitives (J1 artifact, J2 removal, J3 diagnostics). Mid-phase, the project pivoted to the **Control Plane v2 vision** ([docs/superpowers/specs/2026-04-24-control-plane-v2-vision-design.md](superpowers/specs/2026-04-24-control-plane-v2-vision-design.md)), which reordered priorities around five cross-cutting subsystems (M1-M5). Several "must not do" items from the old plan were explicitly overridden — Prometheus scrape (M2.7-M2.8) and multi-user RBAC scaffolding (M5-M5.5) — because the vision treated them as foundational to a usable v2 product, not Phase-3 infrastructure.

This document is the consuntivo of what the pivot actually shipped. The original Phase 2 wishlist that **did not** ship is carried forward to [phase-3-operational-maturity.md](phase-3-operational-maturity.md).

## 2. Subsystems shipped

### M1 — Multi-deploy data model

Schema migration from a single `config` row to first-class `deploys` and `deploy_versions` tables (monotonic `version_n` per deploy, parent chain, audit-trail rollback semantics — rollbacks produce a new forward version). `DeployRepository` with cross-deploy validation (component_id collision and host port collision). Endpoints: `GET/POST/DELETE /api/deploys`, `POST /api/deploys/{id}/{validate,diff,apply,rollback}`, `GET /api/deploys/{id}/versions`. Backwards-compatible shim on `/api/config/*` against a materialized `default` deploy.

**74 unit tests + Playwright 10/10.**

### M2 / M2.5 / M2.6 / M2.7 / M2.8 — Telemetry stack

- **M2 backend.** `metric_samples` and `metric_events` tables with rolling retention; `MetricsRepository` (write/range/list_events/cleanup_older_than); `metrics/contract.py` permissive parser; `metrics/handler.py` registered as Hub event handler; `metrics/retention.py` async task configurable via `MAESTRO_METRICS_RETENTION_INTERVAL_S`; REST `GET /api/metrics/{scope}/{id}` and `GET /api/events`.
- **M2 daemon.** `metrics.CollectHost` via gopsutil (CPU%, RAM%, load1); `PublishMetrics` payload v1 (host + per-component healthcheck); `metricsrunner/` package to break import cycle; `platform_windows.go` stub for dev builds.
- **M2.5 frontend live wiring.** `UIEventBus` pub/sub, `/ws/ui` endpoint with hello + ping/pong + bounded queue 256, reconnecting `RealtimeClient` (1s→30s backoff, 20s heartbeat), `useRealtime` / `useRecentFrames` hooks, `LiveIndicator` in topbar, per-host strip on DeployDetail (current CPU% + 15-min sparkline), TanStack Query cache + 10s polling + WS invalidation.
- **M2.6 deep metrics.** `metrics.ParseDockerStats` + `CollectDocker` via `docker stats --no-stream`; container name convention `maestro-<component_id>`; per-component CPU% and RAM% samples; `useComponentMetric` hook; `/deploys/:id/metrics` view with AreaChart grid (host CPU/RAM + container CPU/RAM per component); `DeploySparkline` on Overview cards.
- **M2.7 log rate + Prometheus scrape (daemon).** `metrics.CollectLogRates` via `docker logs --since 30s | wc -l`; `metrics.ParsePromExposition` + `CollectPrometheus` (Prometheus text format with allow-list to bound cardinality, ms-epoch timestamp stripping).
- **M2.8 declarative scrape (CP).** Pydantic `MetricsSpec` (endpoint http(s) + non-empty allow); `ComponentSpec.metrics` optional; renderer ferries to daemon; daemon `state.Component.{metrics_endpoint, metrics_allow}` columns (ALTER TABLE migration); `Orchestrator.promTargetsFromComps()` derives Prometheus targets from Store on every tick — no static field, auto-adapts to deploy/undeploy.

**135 CP unit tests + all Go packages green; Playwright 6/6 (M2.6) + 5/5 (M2.5).**

### M3 / M3.5 — Polymorphic deploy wizard

- **M3 (docker, new deploy).** `app/wizard/docker_inspect.py` (`parse_docker_inspect` pure + `inspect_image` via `subprocess.run` + `asyncio.to_thread`, 60s pull / 10s inspect timeout, best-effort fallback); `POST /api/wizard/docker/inspect`. Frontend: `web-ui/src/wizard/{types.ts,yamlgen.ts}` (pure YAML generator), 6-step screen (Intent → Source → Source details with Inspect image → Placement → Runtime → Review), `validateStep` gating, Review with diff and "Create deploy + apply" CTA.
- **M3.5 (git + archive sources, add-component / upgrade-component flows).** `WizardState` extended for 3 entry points and 3 source types; `yamlgen.ts` exposes `generateYaml` (new) + `patchYaml` (add/upgrade); Review fetches current YAML and applies patch in-place; "Apply patch" CTA replaces "Create deploy + apply" in non-new flows; URL params `/wizard?entry=&deploy=&component=` for deep links.

**Playwright 8/8 (M3) + 12/12 (M3.5).**

### M4 — React SPA

Vite + TypeScript + Tailwind scaffold at [web-ui/](../web-ui/). Ported primitives (StatusDot, Badge, Pill, Sparkline, AreaChart, Icons, Mono, relTime), `shell.tsx` (sidebar+topbar+theme toggle), `api/client.ts` with TanStack Query hooks, screens for Overview, DeployDetail (version timeline + rollback), Nodes, Wizard (M3+M3.5), Admin, Login. FastAPI serves `web-ui/dist/` with catch-all client-routing. The HTMX dashboard is fully replaced.

**Playwright 9/9 initial + extensions.**

### M5 / M5.5 — Auth and multi-tenant

- **M5 session-based MVP.** `app/auth/passwords.py` PBKDF2-SHA256 stdlib-only hasher (600k iter, 6 unit tests); `UsersRepository` (create / get / get_by_username / count_non_singleuser); `CurrentUserMiddleware` reads `request.scope.session` (bypass to `singleuser` if `MAESTRO_SINGLE_USER_MODE=true`, default ON); starlette `SessionMiddleware` (itsdangerous, signed HttpOnly SameSite=Lax 7-day cookie, `MAESTRO_SESSION_SECRET` env). Endpoints: `POST /api/auth/{setup-admin,login,logout}`, `GET /api/auth/me`. Frontend: `AuthProvider` + `useAuth` hook (loading / single-user / anonymous / authenticated states), `RequireAuth` redirect to `/login`, `LoginScreen`, `UserMenu`. **Middleware order resolved**: `CurrentUserMiddleware` added first (innermost), `SessionMiddleware` after (outermost). 7 auth unit tests (124 CP total) + Playwright 8/8.
- **M5.5 orgs + nodes + ACL + admin UI.** `organizations`, `org_members`, `nodes` (`node_type='user'|'shared'`), `node_access` schemas. `NodesRepository` + `OrganizationsRepository`. `Hub.add_register_handler` callback auto-creates a node row on daemon connect (owner = first admin, or singleuser). API: `GET /api/nodes` (visibility-filtered: owner / explicit grant / org membership / admin sees all), `GET /api/admin/users` (admin-only), `GET/POST /api/orgs`. Frontend: **Nodes** screen (per-node card with online/offline, type pill, owner, 15-min CPU sparkline) and **Admin** screen (users table + orgs CRUD). 130 CP tests + Playwright 7/7.

### Operational artifacts (installer Layer 1)

[docs/superpowers/specs/2026-04-22-installer-scripts-design.md](superpowers/specs/2026-04-22-installer-scripts-design.md) Layer 1 shipped: `install-cp.sh`, `install-daemon.sh` (both with `--upgrade`), GHCR image `ghcr.io/enzinobb/maestro-cp`, multi-arch binaries (linux/amd64+arm64, darwin/amd64+arm64), shared-token enrollment via `POST /api/enroll/<token>/consume`. Subsequent admin work (PR #24) added user role/delete actions, node type pivot, and **non-admin host enroll**.

### MCP API-key auth

[docs/superpowers/specs/2026-04-28-mcp-api-key-auth-design.md](superpowers/specs/2026-04-28-mcp-api-key-auth-design.md) shipped (PR #23): personal API keys for MCP clients, scoped to a user, persisted hashed.

## 3. Deviations from the original `phase-2-beta.md`

`phase-2-beta.md` has been removed. This table preserves the audit trail.

| Original prescription | Outcome | Carry-over |
|---|---|---|
| Group A — Phase 2 schema fields | Partial: schema accepts `deploy_mode`, `strategy: canary`, `credentials_ref` (telaio); `tests`, `resources`, `defaults`, `artifact`, `self_update` not added | P3 §A, §C, §F |
| Group B — Encrypted credential vault | Not shipped | P3 §D |
| Group C — Git-sync auto-deploy (poller + webhook) | Not shipped (wizard accepts `source.type: git` but no auto-redeploy pipeline) | P3 §E |
| Group D — Component test framework | Not shipped | P3 §C |
| Group E — Hot / blue-green / canary | Not shipped (schema-only) | P3 §A |
| Group F — Automatic rollback | Manual rollback shipped (M1); auto-trigger on healthcheck/test failure not shipped | P3 §B |
| Group G — Full MCP + skill | 9 verbs shipped, 10 missing | P3 §G |
| Group H — Rich UI | **Shipped, differently** (Vite+React+Tailwind+TanStack Query+Recharts+custom components instead of shadcn/ui) | — |
| Group I — Updated packaging | Layer 1 shipped (image + binaries + installer scripts); `scripts/backup.sh` not shipped | P3 §K |
| Group J1 — Artifact upload + self-update | Not shipped | P3 §F.1 |
| Group J2 — Component removal + prune | Not shipped (`to_remove` still skipped in diff) | P3 §F.2 |
| Group J3 — Host diagnostics | Not shipped (M2 metrics cover sampling but not aggregated one-shot snapshot) | P3 §F.3 |

`phase-2-beta.md §7` "Things you must not do" overrides:

- ❌ "Do not introduce integrated Prometheus" — overridden by M2.7-M2.8 (declarative scrape via `MetricsSpec`).
- ❌ "Do not introduce multi-user RBAC: UI stays accessible without auth or with a single admin token" — overridden by M5/M5.5 (sessions, orgs, node ACL, admin UI). Note: granular per-action RBAC enforcement is still deferred to P3 §H.

§7 still respected: no Postgres migration, no Kubernetes, no full HA.

## 4. Quality at the close of Phase 2

- 135 CP unit tests + Go packages green.
- ~50 Playwright specs across M1-M5.5 wizard / admin / nodes / auth / metrics / realtime.
- Two real Ubuntu VPS targets continuously deployed (host1 = CP + daemon, host2 = daemon).

## 5. M4.5 — DeployDetail consolidation (shipped)

The two inert tabs on DeployDetail ("Components", "Configuration") are now interactive. Plan: [docs/superpowers/plans/2026-04-30-m4.5-deploy-detail.md](superpowers/plans/2026-04-30-m4.5-deploy-detail.md).

**L.1 — Components tab.**
- Per-component cards rendered from a generalised YAML parser ([web-ui/src/lib/yamlparse.ts](../web-ui/src/lib/yamlparse.ts), extracted from the inline `extractHostIds` regex). Source summaries: `image:tag` for docker, `repo@ref` for git, `path` for archive.
- Status pill derived from `/api/state` (legacy single-config endpoint, joined by `component_id`). Maps `running -> healthy`, `unhealthy/failed -> failed`, `stopped/host_offline -> offline`, anything else -> `unknown`.
- Inline CPU% + RAM% sparklines via the M2.6 `useComponentMetric` hook; live via the existing TanStack Query 10s poll plus `/ws/ui` invalidation.
- "View logs" link to a new preview screen at `/components/:id/logs` (calls `GET /api/components/{id}/logs?lines=200`, refetches every 5s; streaming deferred to Phase 3 §G).
- Empty `<div class="cp-component-card__actions" />` reserved for Phase 3 action buttons (grep marker documented in code).

**L.2 — Configuration tab.**
- CodeMirror 6 viewer (`@codemirror/state` + `@codemirror/view` + `@codemirror/lang-yaml`, all lazy-loaded so the editor only enters the bundle on first open).
- Version dropdown lists all `data.versions` newest-first; selection switches the viewer.
- "Diff vs current" toggle uses `@codemirror/merge` MergeView side-by-side.
- "Edit raw YAML" enters edit mode with three actions wired to existing M1 endpoints: **Validate** -> `POST /api/deploys/{id}/validate`, **Diff vs current** -> `POST /api/deploys/{id}/diff`, **Apply** -> `POST /api/deploys/{id}/apply`. Apply is gated on a green Validate against the current buffer; any keystroke invalidates prior validate/diff results.
- Apply opens a `ConfirmApplyDialog` summarising created/updated/removed counts and explicitly warning that "components removed in YAML are NOT removed from hosts (Phase 2 backcompat)".

**Tab routing.** `?tab=versions|components|configuration` query param via `useSearchParams`; Metrics remains a separate route (`/deploys/:id/metrics`) reached via `<Link>`.

**Tests.**
- Vitest: `web-ui/src/lib/yamlparse.test.ts` — 9 cases, all green.
- E2E: ad-hoc Playwright script written to `/tmp/playwright-test-m4.5.js` and run via the local playwright skill — 12 checks green (login + the 9 spec acceptance steps + 2 status-pill / metric-row sub-checks).

**Bundle delta.** 171.4 KB gzipped (152.8 KB CodeMirror lazy-chunks + ~18 KB core + CSS), within the 200 KB budget. Baseline 115.83 KB total gzipped → after-M4.5 287.23 KB total gzipped.

**Deviations from the original §5 spec:**
- Tab state via `?tab=` query param (spec said "URL param or local state, your call").
- `/api/components/{id}/logs` parameter is `lines=`, not `tail=` as the spec wrote — spec error, code uses the correct parameter.
- "Components (M2.6)" badge dropped — M2.6 shipped the metrics hooks, not this tab; the label was a misnomer.
- Per-deploy state endpoint not introduced (the spec doesn't ask for one and the legacy `/api/state` covers Phase 2 needs).
- Playwright runner: spec referenced `tests/playwright/deploy-detail-m45.spec.ts`; the project's actual practice is ad-hoc `/tmp` scripts run via the playwright skill (no committed runner). Followed the project convention.
- The 9th e2e step ("Apply → confirm → version timeline refetched") was demoted to "Apply opens confirm dialog → cancel" because the smoke environment had no daemon connected; confirming would have produced a 502 from the engine, not a real assertion of the dialog wiring. The full happy-path is exercised manually on the two-VPS test environment.

**Out of scope (deferred to Phase 3):**
Per-component action buttons, drift badge, tests-history panel, streaming logs, structured-field replacement of the regex YAML parser. All match the spec's "Out of scope" list.

## 6. Carry-forward

- Active work plan: [phase-3-operational-maturity.md](phase-3-operational-maturity.md).
- Production-scale work: [phase-4-production-scale.md](phase-4-production-scale.md).
- Roadmap: [roadmap.md](roadmap.md).
