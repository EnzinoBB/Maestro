# Control Plane ↔ Daemon Protocol

This document describes the communication protocol between the control plane
and the `maestrod` daemons. The transport is WebSocket over TLS (in production).
Messages are encoded as JSON.

## 1. Connection establishment

### Handshake phase

The daemon opens a WebSocket connection toward the control plane endpoint
(default `wss://<control-plane>/ws/daemon`) and includes the following HTTP
headers:

```
Authorization: Bearer <daemon_token>
X-Maestro-Daemon-Id: <unique_daemon_id>
X-Maestro-Daemon-Version: <version_string>
X-Maestro-Host-Info: <base64(json with hostname, os, arch, kernel)>
```

The control plane validates the token, registers the daemon in the hub, and
responds with a successful WebSocket upgrade. If authentication fails, a 401
is returned and the daemon retries after backoff.

After the upgrade, the first message is a `hello` sent by the control plane:

```json
{
  "id": "ctl-0001",
  "type": "hello",
  "payload": {
    "server_version": "1.0.0",
    "assigned_host_id": "api-server",
    "heartbeat_interval_sec": 15,
    "session_id": "s-c3f1..."
  }
}
```

The daemon replies with `hello_ack`, which includes a summary of its current
state:

```json
{
  "id": "dmn-0001",
  "type": "hello_ack",
  "in_reply_to": "ctl-0001",
  "payload": {
    "daemon_version": "1.0.0",
    "runners_available": ["systemd", "docker"],
    "components_known": [
      {"id": "api", "component_hash": "a1b2...", "status": "running"},
      {"id": "db",  "component_hash": "f9e8...", "status": "running"}
    ],
    "system": {"cpu_count": 4, "total_mem_mb": 8192}
  }
}
```

## 2. Message envelope

Every message has the form:

```json
{
  "id": "<unique message string>",
  "type": "<string: category.name>",
  "in_reply_to": "<id of the requested message, if a reply>",
  "payload": { ... },
  "ts": "2026-04-21T10:23:00Z"
}
```

Rules:

- `id` is a UUIDv4 or a monotonic string, chosen by the sender.
- Synchronous replies set `in_reply_to`.
- Asynchronous events (pushed by the daemon) do not set `in_reply_to`.
- `ts` is optional but recommended, in ISO 8601 UTC.

## 3. Taxonomy of `type`

Types follow the convention `direction.category.name`:

- `request.*` — request expecting a reply
- `response.*` — synchronous reply
- `event.*` — asynchronous notification
- `ping`, `pong` — heartbeat
- `hello`, `hello_ack`, `bye` — lifecycle

## 4. Requests from the control plane to the daemon

### `request.state.get`

```json
{
  "id": "ctl-0010",
  "type": "request.state.get",
  "payload": {
    "components": ["api"]    // optional; if absent, all
  }
}
```

Reply:

```json
{
  "id": "dmn-0042",
  "in_reply_to": "ctl-0010",
  "type": "response.state.get",
  "payload": {
    "components": [
      {
        "id": "api",
        "status": "running",         // running | stopped | failed | deploying | unknown
        "component_hash": "a1b2...",
        "git_commit": "c9d4e2f",
        "runner": "systemd",
        "pid": 12345,
        "started_at": "2026-04-20T09:00:00Z",
        "last_healthcheck": {
          "ok": true,
          "ts": "2026-04-21T10:22:45Z"
        },
        "metrics": {
          "cpu_pct": 2.1,
          "rss_mb": 128,
          "restarts_since_deploy": 0
        }
      }
    ]
  }
}
```

### `request.deploy`

The most important message. The control plane provides the daemon with
everything it needs to deploy a component.

```json
{
  "id": "ctl-0020",
  "type": "request.deploy",
  "payload": {
    "component_id": "api",
    "target_hash": "7a9b...",
    "deploy_mode": "cold",
    "source": {
      "type": "inline_tarball",     // tarball of the code, base64
      "data": "H4sIAAAAAAA..."
      // or type=git with credentials for the daemon-side clone
      // or type=docker_image and tag
    },
    "build_steps": [
      {"command": "npm ci", "working_dir": ".", "env": {}}
    ],
    "config_files": [
      {"dest": "/opt/demo-api/.env", "mode": 420, "content_b64": "..."}
    ],
    "config_archives": [
      {
        "dest": "/var/www/site",
        "strategy": "atomic_symlink",
        "mode": 493,
        "tar_b64": "H4sIA...",
        "content_hash": "a1b2..."
      }
    ],
    "run": { ... },              // the entire ComponentSpec.run
    "secrets": {                 // volatile, never persisted to disk by the daemon
      "DB_PASSWORD": "xxx"
    },
    "healthcheck": { ... },
    "timeout_sec": 900
  }
}
```

`config_archives` carries tar-bundled directory material. Each entry has a
strategy (`overwrite`, `atomic`, `atomic_symlink`) that determines how the
daemon materializes it on the host. For `atomic_symlink` the daemon keeps
the last 5 releases under `<dest>/releases/<content_hash>/` and flips
`<dest>/current` atomically.

Reply (synchronous, may arrive at the end of the deployment):

```json
{
  "in_reply_to": "ctl-0020",
  "type": "response.deploy",
  "payload": {
    "ok": true,
    "component_id": "api",
    "new_hash": "7a9b...",
    "duration_ms": 45200,
    "phases": [
      {"name": "fetch",    "ok": true, "duration_ms": 3100},
      {"name": "build",    "ok": true, "duration_ms": 38000},
      {"name": "stop_old", "ok": true, "duration_ms": 800},
      {"name": "swap",     "ok": true, "duration_ms": 1200},
      {"name": "start",    "ok": true, "duration_ms": 600},
      {"name": "health",   "ok": true, "duration_ms": 1500}
    ]
  }
}
```

On error:

```json
{
  "in_reply_to": "ctl-0020",
  "type": "response.deploy",
  "payload": {
    "ok": false,
    "component_id": "api",
    "error": {
      "code": "build_failed",
      "phase": "build",
      "message": "npm ci exited with code 1",
      "details": {
        "stderr_tail": "npm ERR! could not resolve package...",
        "missing_dependency": "libpq-dev"
      },
      "suggested_fix": "install libpq-dev on host and retry"
    }
  }
}
```

### Standard error codes

| Code | Meaning |
|------|---------|
| `validation_error` | Payload does not conform to the expected schema |
| `auth_error` | Authentication issues against registry/git |
| `fetch_failed` | Unable to fetch sources/images |
| `build_failed` | Error during the build |
| `dependency_missing` | Missing system dependency |
| `config_error` | Invalid config template or unresolved variable |
| `runtime_error` | Error while starting the component |
| `healthcheck_failed` | Component started but healthcheck failed |
| `timeout` | Operation timed out |
| `conflict` | Current state incompatible with the action |
| `not_found` | Component does not exist |
| `internal` | Daemon internal error |

### Other requests

- `request.start` — starts a component already installed
  ```json
  { "payload": {"component_id": "api"} }
  ```
- `request.stop` — stops a component
  ```json
  { "payload": {"component_id": "api", "graceful_timeout_sec": 30} }
  ```
- `request.restart` — stop + start
- `request.rollback` — reverts to the previous saved hash
  ```json
  { "payload": {"component_id": "api", "steps_back": 1} }
  ```
- `request.logs.tail` — asks for recent logs
  ```json
  { "payload": {"component_id": "api", "lines": 200, "since": "2026-04-21T09:00:00Z"} }
  ```
- `request.logs.stream` — starts a stream (see §7)
- `request.healthcheck.run` — forces an immediate healthcheck
- `request.tests.run` (Phase 2) — runs the declared tests
- `request.metrics.snapshot` — asks for an instant sample

## 5. Asynchronous events from the daemon

Published without `in_reply_to`. The control plane dispatches them to the
observers (UI, orchestrator, storage).

### `event.metrics`

Sent periodically (default every 30s) with a metric snapshot for all
components:

```json
{
  "type": "event.metrics",
  "payload": {
    "ts": "2026-04-21T10:23:00Z",
    "components": [
      {"id": "api", "cpu_pct": 2.1, "rss_mb": 128, "fd": 42},
      {"id": "db",  "cpu_pct": 1.3, "rss_mb": 512, "fd": 89}
    ],
    "host": {"load_avg_1m": 0.4, "disk_usage_pct": 63}
  }
}
```

### `event.status_change`

```json
{
  "type": "event.status_change",
  "payload": {
    "component_id": "api",
    "from": "running",
    "to": "failed",
    "reason": "process exited with code 137"
  }
}
```

### `event.healthcheck_failed`

```json
{
  "type": "event.healthcheck_failed",
  "payload": {
    "component_id": "api",
    "consecutive_failures": 3,
    "last_check": {
      "type": "http",
      "url": "http://localhost:3000/health",
      "error": "connection refused"
    }
  }
}
```

### `event.drift_detected` (Phase 2)

Emitted when the daemon notices that something has changed outside its control
(e.g. someone ran `systemctl stop` manually).

```json
{
  "type": "event.drift_detected",
  "payload": {
    "component_id": "api",
    "expected": "running",
    "observed": "stopped"
  }
}
```

### `event.log`

Only during an active stream. One message per line (or in batches).

```json
{
  "type": "event.log",
  "payload": {
    "stream_id": "s-1234",
    "component_id": "api",
    "lines": [
      {"ts": "2026-04-21T10:23:00.123Z", "level": "INFO", "msg": "listening on :3000"}
    ]
  }
}
```

## 6. Heartbeat and reconnection

- Both sides send `ping` every `heartbeat_interval_sec` (default 15s).
- The receiver replies with `pong` on the same id.
- If no `pong` arrives for 3 consecutive intervals, the connection is
  considered dead and closed.

When the daemon loses the connection:

1. It internally marks its state as "offline" (but keeps managing the local
   processes).
2. It attempts to reconnect with exponential backoff: 1s, 2s, 4s, 8s, ...,
   capped at 60s. Jitter ±20%.
3. On reconnect, it repeats the handshake. If the local `component_hash`
   diverges from what the control plane has in memory (because something
   happened offline), reconciliation kicks in: the control plane treats the
   daemon's state as authoritative.

## 7. Streaming

Some operations support streaming (logs, real-time build output). The
protocol:

1. The control plane sends `request.logs.stream` with a `stream_id` in the
   payload.
2. The daemon replies immediately with `response.logs.stream.started`.
3. The daemon publishes `event.log` with the same `stream_id` until:
   - `request.logs.stream.cancel` from the control plane, or
   - `event.log.stream_ended` from the daemon (component terminated)

## 8. Message size

- Hard limit: 4 MB per message.
- Larger deploy tarballs → use `source.type: git` (daemon-side clone) or
  out-of-band upload via HTTP with a signed URL (Phase 2).
- Log streaming: batch every 500ms or every 100 lines.

## 9. Protocol versioning

The handshake includes `server_version` and `daemon_version`. Rules:

- Same major version → compatibility guaranteed.
- Different major version → connection rejected with a clear message.
- Different minor version → allowed; features not supported by the older
  side return `unsupported_operation`.

New fields are added additively; removals require a major-version bump.

## 10. Security

- TLS always, except in explicit local development (`--insecure`).
- Pre-shared token managed by the control plane; can be revoked.
- In production (Phase 3): mutual TLS with per-daemon certificates.
- All secrets in the `request.deploy` payload are considered volatile; the
  daemon never writes them to persistent disk and only passes them as
  environment variables to child processes.
- Audit log of all messages sent/received on the control-plane side.
