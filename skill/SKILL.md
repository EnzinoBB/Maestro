---
name: maestro-orchestrator
description: >
  Pilots the Maestro system to deploy, monitor, and
  manage application components on Linux machines and, from Phase 3 on, on
  Kubernetes clusters. Use it when the user asks to modify deployment
  configurations, start/stop/restart components, check deploy status, read
  logs or metrics, run component tests, or perform rollbacks. The skill
  relies on the MCP server exposed by the Maestro control plane.
---

# Maestro Orchestrator Skill

This skill guides an AI agent in using the Maestro control plane's MCP
server. It is designed to reduce token usage by exposing a clear mental
model and a standardized operational flow.

> Note: this is the **skeleton** produced in Phase 0. It will be enriched
> in Phase 2 with full decision flows and in Phase 3 with sections
> dedicated to Kubernetes, RBAC, and advanced workflows.

## Mental model

The Maestro system manages projects described by a `deployment.yaml` file
that enumerates **hosts** (where to deploy) and **components** (what to
deploy), with an assignment plan `deployment[]`. Each component has a
`deploy_mode` (`cold`, `hot`, `blue_green`) and comes with a `healthcheck`
and, optionally, with `tests`.

Three actors:

1. **Control plane** (Python): reads the YAML, orders the operations, talks
   to the daemons.
2. **Daemon** (`maestrod`, Go): a process running on each host that knows
   the local state and executes the requested actions.
3. **Agent (you)**: you operate via the control plane's MCP server.

## Available MCP verbs

Query them through the MCP `list_tools` tool if unsure. In Phase 1:

| Tool | Input | Output |
|------|-------|--------|
| `list_hosts` | — | Array of hosts with status, tags, assigned components |
| `get_state` | `project?` | Aggregate state of all components |
| `get_component_state` | `component_id` | Detailed state of a single component |
| `validate_config` | `yaml_text` | OK or a list of errors with path and message |
| `apply_config` | `yaml_text, dry_run?` | Diff + apply confirmation |
| `deploy` | `project?, component_id?` | Starts a synchronous or async deploy |
| `start` / `stop` / `restart` | `component_id` | Operation outcome |
| `tail_logs` | `component_id, lines?` | Array of lines |

Starting in Phase 2: `rollback`, `run_tests`, `get_deployment_history`,
`get_metrics`, `drift_status` are added.

## Standard operational flow

The recommended flow for **every change** to the configuration:

1. **Validate**. Call `validate_config` with the proposed YAML. If there
   are errors, fix them before proceeding; **do not** move to
   `apply_config` until validation is clean.
2. **Diff**. Call `apply_config` with `dry_run: true`. Show the user which
   components will be created, modified, or removed.
3. **Confirm**. Wait for explicit user confirmation before applying.
4. **Apply**. Call `apply_config` with `dry_run: false`. Receive a deploy
   handle.
5. **Watch**. Poll `get_state` (every 2-5s) until all impacted components
   are in a terminal state (`running`, `failed`).
6. **Verify**. Read any failed healthchecks or error logs; report a
   summary to the user.
7. **Rollback** (if needed): only if the outcome is unsatisfactory and the
   user explicitly asks for it, invoke `rollback` (Phase 2+).

## Error handling

Errors from the MCP server have the shape:

```json
{
  "code": "build_failed",
  "message": "npm ci exited with code 1",
  "details": { ... },
  "suggested_fix": "install libpq-dev on host"
}
```

Recommended actions per code (initial list — will be extended):

- `validation_error` → show the errors path-by-path to the user; do not
  retry.
- `auth_error` (Git/registry) → verify credentials in the vault, ask the
  user to update them if missing.
- `dependency_missing` → if `suggested_fix` proposes an `apt install`,
  relay the instruction to the user (in Phase 1 the agent does not run
  shell commands on the host).
- `healthcheck_failed` → read the logs (`tail_logs`), extract the last
  error lines, propose a rollback.
- `timeout` → increase `timeout_sec` if plausible, or flag a potential
  stall.
- `conflict` → the current state prevents the action; read the state
  first.
- `not_found` → verify that the `id` exists.

## Token-efficient usage conventions

1. **Do not download entire logs**. Use `tail_logs` with `lines: 50-200`.
   If more is needed, ask for a filter by level or timestamp.
2. **Do not poll aggressively**. A 3-5 second interval is enough.
3. **Compress the state**. When showing state to the user, summarize (e.g.
   "3/3 components running, healthcheck OK") instead of dumping the JSON.
4. **Errors before anything else**. If a tool returns an error, analyze it
   immediately; do not carry on with the flow as if it had succeeded.

## Anti-patterns

- **Do not** edit files directly on the daemons' disks via other channels
  (SSH, etc.). Everything goes through the control plane.
- **Do not** start a `deploy` without first running `validate_config` and
  having shown the diff to the user.
- **Do not** call `start`/`stop` repeatedly as a surrogate for restart:
  use `restart` directly.

## Example dialogues

**User**: "Add a second redis component to the demo project and deploy it
on host1."

1. `get_state` → understand what's there.
2. Propose to the user an updated YAML that adds the `cache` component
   with `source.type: docker, image: redis`.
3. `validate_config` with the proposed YAML.
4. `apply_config` with `dry_run: true` → show diff ("+ cache").
5. User confirmation.
6. `apply_config` with `dry_run: false`.
7. Poll `get_state` until `cache` is running.
8. Summary: "cache deployed, healthcheck green."

**User**: "The API service isn't responding."

1. `get_component_state component_id=api`.
2. If `status: failed` or `healthcheck` failing: `tail_logs api lines=100`.
3. Analyze the last lines; if a known pattern (e.g. "connection refused to
   database"), report the cause.
4. Propose `restart` or, in Phase 2+, `rollback` to the last green
   version.

## Evolution

This document grows with the product:

- **Phase 1**: this skeleton.
- **Phase 2**: add sections on tests, rollback, hot deploy, canary,
  git-sync, vault.
- **Phase 3**: add Kubernetes, RBAC, observability, multi-environment
  workflows.
