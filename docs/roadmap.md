# Development roadmap

The project is planned in **four** incremental phases. Each phase produces a usable artifact and is documented by a dedicated file (`phase-N-*.md`) designed to be consumed by an AI agent together with the code from previous phases, enabling iterative development with low token usage.

## Phase summary

| Phase | Name | Status | Goal |
|-------|------|--------|------|
| 1 | Prototype | **closed** | Working vertical slice: real deployment of a Docker component from YAML on real Linux hosts. |
| 2 | Control Plane v2 | **closed** | Multi-deploy data model, telemetry stack, polymorphic deploy wizard, React SPA, multi-tenant auth, MCP API-key auth, installer Layer 1, M4.5 DeployDetail consolidation. |
| 3 | Operational Maturity | active | Hot/blue-green/canary, automatic rollback, test framework, vault, git-sync auto-deploy, granular lifecycle primitives (artifact + self-update + remove + diagnostics), MCP completeness, RBAC enforcement, audit log, hardening, backup. |
| 4 | Production Scale | planned | Kubernetes runner, Postgres + Alembic, HA + leader election, mTLS, OIDC, `maestro` CLI, professional packaging (.deb/.rpm + Helm), documentation site, OpenTelemetry. |

## Phase documents

- Phase 1: [docs/phase-1-completion.md](phase-1-completion.md) — historical record of what shipped in the prototype.
- Phase 2: [docs/phase-2-completion.md](phase-2-completion.md) — consuntivo of the CP v2 trajectory (M1 multi-deploy, M2-M2.8 telemetry, M3-M3.5 wizard, M4 SPA, M5-M5.5 multi-tenant), plus operational artifacts (installer Layer 1, MCP API-key auth, non-admin enroll).
- Phase 3: [docs/phase-3-operational-maturity.md](phase-3-operational-maturity.md) — active work plan.
- Phase 4: [docs/phase-4-production-scale.md](phase-4-production-scale.md) — forward plan.

## Architectural reference

- [docs/architecture.md](architecture.md) — system architecture (three-tier CP / daemon / agent).
- [docs/yaml-schema.md](yaml-schema.md) — YAML schema reference.
- [docs/protocol.md](protocol.md) — daemon ↔ CP wire protocol.
- [docs/superpowers/specs/2026-04-24-control-plane-v2-vision-design.md](superpowers/specs/2026-04-24-control-plane-v2-vision-design.md) — CP v2 vision (M1-M5 umbrella).
- [docs/superpowers/specs/2026-04-22-installer-scripts-design.md](superpowers/specs/2026-04-22-installer-scripts-design.md) — installer scripts and enrollment design.
- [docs/superpowers/specs/2026-04-28-mcp-api-key-auth-design.md](superpowers/specs/2026-04-28-mcp-api-key-auth-design.md) — MCP API-key auth.

## Phase transition rules

A phase is considered closed when:

1. Every task in the phase document is resolved (or explicitly deferred to a successor phase, with the deferral recorded).
2. Every acceptance test of the phase passes.
3. The system starts up and serves the documented commands without manual intervention.
4. A `phase-N-completion.md` document captures any deviation from the plan.

If a technical choice in a plan turns out to be wrong during implementation, the agent has a mandate to deviate, recording the deviation in the relevant `phase-N-completion.md`. Phase 2 is itself an example: the plan was `phase-2-beta.md`, the trajectory shifted to the CP v2 vision, and the consuntivo is in [phase-2-completion.md](phase-2-completion.md).

## How to feed the documents to an agent

For Phase 3 work, provide:
- the repository as it stands at end of Phase 2,
- [docs/architecture.md](architecture.md),
- [docs/yaml-schema.md](yaml-schema.md),
- [docs/protocol.md](protocol.md),
- [docs/phase-3-operational-maturity.md](phase-3-operational-maturity.md),
- [docs/phase-2-completion.md](phase-2-completion.md) for context.

Each phase document is intentionally self-contained: it lists prerequisites, tasks, acceptance criteria, and tests to run.
