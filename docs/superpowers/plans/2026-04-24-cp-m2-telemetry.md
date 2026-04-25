# CP v2 M2 — Telemetry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the metrics pipeline end-to-end: daemon collects host + per-component metrics, pushes them via the existing WS as `event.metrics`, the CP persists them in a rolling-window SQLite store and exposes time-series + event APIs.

**Architecture:** Define a stable `event.metrics` payload contract; CP routes incoming `event.metrics` envelopes through a new event handler into a `MetricsRepository` (SQLite, two tables: `metric_samples` rolling 24h, `metric_events` retained capped). New `/api/metrics/*` + `/api/events` endpoints serve range queries shaped for direct Recharts consumption. Daemon enriches its existing `PublishMetrics` with host CPU/RAM/load (gopsutil) plus per-component healthcheck latency.

**Tech Stack:** Python 3.11, FastAPI, aiosqlite, pytest, pytest-asyncio. Go 1.22, github.com/shirou/gopsutil/v3.

**Spec reference:** [docs/superpowers/specs/2026-04-24-control-plane-v2-vision-design.md](../specs/2026-04-24-control-plane-v2-vision-design.md), §2.

**Out of scope (deferred to follow-up M2.5 / M2.6):**
- `/ws/ui` browser fan-out (events only flow into the DB in M2; UI polls).
- Per-container CPU/RAM (requires Docker stats wiring in daemon).
- Custom Prometheus scrape from component-declared `/metrics` endpoints.
- Log line-rate metric (daemon-side log tailer).

---

## File Structure

Files created:
- `control-plane/app/storage_metrics.py` — `MetricsRepository` (SQLite, rolling window + range query)
- `control-plane/app/metrics/__init__.py` — package marker
- `control-plane/app/metrics/contract.py` — typed parsing of `event.metrics` payloads
- `control-plane/app/metrics/handler.py` — Hub event handler: persists samples + events
- `control-plane/app/metrics/retention.py` — periodic rolling-window cleanup task
- `control-plane/app/api/metrics.py` — `/api/metrics/*` and `/api/events` REST router
- `control-plane/tests/unit/test_storage_metrics.py`
- `control-plane/tests/unit/test_metrics_contract.py`
- `control-plane/tests/unit/test_metrics_handler.py`
- `control-plane/tests/unit/test_metrics_retention.py`
- `control-plane/tests/unit/test_api_metrics.py`
- `daemon/internal/metrics/host.go` — gopsutil-backed host probe
- `daemon/internal/metrics/host_test.go` — unit test (smoke; just non-empty)

Files modified:
- `control-plane/app/storage.py` — extend `_SCHEMA` with `metric_samples` + `metric_events` tables
- `control-plane/app/main.py` — wire `MetricsRepository`, register handler with Hub, start retention task in lifespan
- `control-plane/app/ws/protocol.py` — keep `T_EV_METRICS`; document the v1 payload shape in a docstring on the constant
- `daemon/internal/orchestrator/orchestrator.go` — replace thin `PublishMetrics` body with v1-shaped payload (host metrics from new `metrics/host.go`, per-component healthcheck latency from `Store`)
- `daemon/go.mod` / `daemon/go.sum` — add gopsutil dependency

Files unchanged:
- `Hub` event-handler API already supports adding handlers (`add_event_handler`).
- The deploy/version model from M1 is consumed read-only when computing deploy-level aggregates.

---

## Payload Contract (the lock-in interface)

The `event.metrics` payload that daemon emits and CP ingests:

```json
{
  "ts": "2026-04-24T11:34:00Z",
  "host_id": "host1",
  "samples": [
    {"scope": "host",      "scope_id": "host1", "metric": "cpu_percent",  "value": 42.1},
    {"scope": "host",      "scope_id": "host1", "metric": "ram_percent",  "value": 71.5},
    {"scope": "host",      "scope_id": "host1", "metric": "load1",        "value": 0.84},
    {"scope": "component", "scope_id": "web",   "metric": "healthcheck_ok",      "value": 1},
    {"scope": "component", "scope_id": "web",   "metric": "healthcheck_latency_ms", "value": 23.4}
  ],
  "events": [
    {"kind": "healthcheck_state_change", "scope": "component", "scope_id": "web",
     "payload": {"from": "ok", "to": "fail", "reason": "5xx"}}
  ]
}
```

`scope` ∈ `host | component | deploy`. Unknown scopes/metrics are dropped silently to keep the daemon free to evolve its emission set without breaking the CP. Samples are persisted as-is; events are persisted as JSON blob keyed by `kind`.

The contract is the source of truth for both sides — Task 3 specifies the parser, Task 7 specifies the daemon emitter. Both reference this section.

---

## Task 1: Schema for metrics tables

**Files:**
- Modify: `control-plane/app/storage.py` — append two CREATE TABLE statements to `_SCHEMA`
- Create: `control-plane/tests/unit/test_storage_metrics.py`

- [ ] **Step 1: Write failing test**

Create `control-plane/tests/unit/test_storage_metrics.py`:

```python
import os
import tempfile
import pytest
import aiosqlite

from app.storage import Storage


@pytest.mark.asyncio
async def test_init_creates_metrics_tables_and_indices():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")
        await Storage(path).init()
        async with aiosqlite.connect(path) as db:
            async with db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name IN ('metric_samples','metric_events')"
            ) as cur:
                tables = sorted(r[0] for r in await cur.fetchall())
            async with db.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name='idx_metric_samples_lookup'"
            ) as cur:
                idx = await cur.fetchall()
        assert tables == ["metric_events", "metric_samples"]
        assert len(idx) == 1
```

- [ ] **Step 2: Run test, verify FAIL**

Run: `cd control-plane && python -m pytest tests/unit/test_storage_metrics.py::test_init_creates_metrics_tables_and_indices -v`
Expected: FAIL — tables missing.

- [ ] **Step 3: Append to `_SCHEMA` in `control-plane/app/storage.py`**

Insert before the closing `"""` of the existing `_SCHEMA` constant:

```python
-- Metrics (M2)
CREATE TABLE IF NOT EXISTS metric_samples (
    ts          REAL NOT NULL,
    scope       TEXT NOT NULL,            -- 'host' | 'component' | 'deploy'
    scope_id    TEXT NOT NULL,
    metric      TEXT NOT NULL,
    value       REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metric_samples_lookup
    ON metric_samples(scope, scope_id, metric, ts);

CREATE TABLE IF NOT EXISTS metric_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            REAL NOT NULL,
    kind          TEXT NOT NULL,
    scope         TEXT NOT NULL,
    scope_id      TEXT NOT NULL,
    payload_json  TEXT
);
CREATE INDEX IF NOT EXISTS idx_metric_events_lookup
    ON metric_events(scope, scope_id, ts DESC);
```

- [ ] **Step 4: Run test, verify PASS**

Run: `cd control-plane && python -m pytest tests/unit/test_storage_metrics.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add control-plane/app/storage.py control-plane/tests/unit/test_storage_metrics.py
git commit -m "feat(cp): add metric_samples and metric_events schema (M2 Task 1)"
```

---

## Task 2: MetricsRepository — write paths

**Files:**
- Create: `control-plane/app/storage_metrics.py`
- Modify: `control-plane/tests/unit/test_storage_metrics.py` — append tests

- [ ] **Step 1: Append failing tests**

```python
from app.storage_metrics import MetricsRepository, MetricSample, MetricEvent


@pytest.mark.asyncio
async def test_record_samples_inserts_rows():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")
        await Storage(path).init()
        repo = MetricsRepository(path)

        await repo.record_samples([
            MetricSample(ts=1000.0, scope="host", scope_id="h1", metric="cpu_percent", value=42.0),
            MetricSample(ts=1000.0, scope="host", scope_id="h1", metric="ram_percent", value=70.5),
        ])

        async with aiosqlite.connect(path) as db:
            async with db.execute(
                "SELECT scope, scope_id, metric, value FROM metric_samples ORDER BY metric"
            ) as cur:
                rows = await cur.fetchall()
        assert rows == [
            ("host", "h1", "cpu_percent", 42.0),
            ("host", "h1", "ram_percent", 70.5),
        ]


@pytest.mark.asyncio
async def test_record_event_inserts_with_payload():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")
        await Storage(path).init()
        repo = MetricsRepository(path)

        await repo.record_event(MetricEvent(
            ts=1000.0, kind="healthcheck_state_change",
            scope="component", scope_id="web",
            payload={"from": "ok", "to": "fail"},
        ))

        async with aiosqlite.connect(path) as db:
            async with db.execute(
                "SELECT kind, scope, scope_id, payload_json FROM metric_events"
            ) as cur:
                rows = await cur.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "healthcheck_state_change"
        assert '"from"' in rows[0][3] and '"fail"' in rows[0][3]


@pytest.mark.asyncio
async def test_record_samples_empty_is_noop():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")
        await Storage(path).init()
        repo = MetricsRepository(path)
        await repo.record_samples([])
        async with aiosqlite.connect(path) as db:
            async with db.execute("SELECT COUNT(*) FROM metric_samples") as cur:
                count = (await cur.fetchone())[0]
        assert count == 0
```

- [ ] **Step 2: Run, verify FAIL**

Run: `cd control-plane && python -m pytest tests/unit/test_storage_metrics.py -v`
Expected: 3 new tests FAIL — `MetricsRepository` missing.

- [ ] **Step 3: Create `control-plane/app/storage_metrics.py`**

```python
"""Time-series and event store backed by SQLite (rolling window)."""
from __future__ import annotations

import aiosqlite
import json
import time
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class MetricSample:
    ts: float
    scope: str
    scope_id: str
    metric: str
    value: float


@dataclass(frozen=True)
class MetricEvent:
    ts: float
    kind: str
    scope: str
    scope_id: str
    payload: dict[str, Any] | None = None


class MetricsRepository:
    """SQLite-backed metrics store. All writes are batched per-call.

    Designed to be swapped for a TSDB later: callers depend on the public
    methods, never on the schema directly.
    """

    def __init__(self, path: str) -> None:
        self.path = path

    # ---------- writes ----------

    async def record_samples(self, samples: list[MetricSample]) -> None:
        if not samples:
            return
        rows = [(s.ts, s.scope, s.scope_id, s.metric, s.value) for s in samples]
        async with aiosqlite.connect(self.path) as db:
            await db.executemany(
                "INSERT INTO metric_samples(ts, scope, scope_id, metric, value) "
                "VALUES (?,?,?,?,?)",
                rows,
            )
            await db.commit()

    async def record_event(self, event: MetricEvent) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO metric_events(ts, kind, scope, scope_id, payload_json) "
                "VALUES (?,?,?,?,?)",
                (
                    event.ts, event.kind, event.scope, event.scope_id,
                    json.dumps(event.payload) if event.payload is not None else None,
                ),
            )
            await db.commit()

    # ---------- reads (Task 3) ----------
    # range / list_events methods are added in Task 3.

    # ---------- maintenance (Task 5) ----------
    # cleanup_older_than is added in Task 6.
```

- [ ] **Step 4: Run, verify PASS**

Run: `cd control-plane && python -m pytest tests/unit/test_storage_metrics.py -v`
Expected: 4 PASS (initial schema test + 3 new write tests).

- [ ] **Step 5: Commit**

```bash
git add control-plane/app/storage_metrics.py control-plane/tests/unit/test_storage_metrics.py
git commit -m "feat(cp): MetricsRepository write paths (samples + events) (M2 Task 2)"
```

---

## Task 3: MetricsRepository — range queries

**Files:**
- Modify: `control-plane/app/storage_metrics.py` — add `range` and `list_events`
- Modify: `control-plane/tests/unit/test_storage_metrics.py` — append tests

- [ ] **Step 1: Append failing tests**

```python
@pytest.mark.asyncio
async def test_range_returns_ordered_samples_in_window():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")
        await Storage(path).init()
        repo = MetricsRepository(path)
        await repo.record_samples([
            MetricSample(ts=100.0, scope="host", scope_id="h1", metric="cpu_percent", value=10.0),
            MetricSample(ts=200.0, scope="host", scope_id="h1", metric="cpu_percent", value=20.0),
            MetricSample(ts=300.0, scope="host", scope_id="h1", metric="cpu_percent", value=30.0),
            # noise on a different metric — must not appear
            MetricSample(ts=200.0, scope="host", scope_id="h1", metric="ram_percent", value=99.0),
            # noise on a different host
            MetricSample(ts=200.0, scope="host", scope_id="h2", metric="cpu_percent", value=88.0),
        ])

        rows = await repo.range(scope="host", scope_id="h1", metric="cpu_percent",
                                from_ts=150.0, to_ts=300.0)
        assert rows == [(200.0, 20.0), (300.0, 30.0)]


@pytest.mark.asyncio
async def test_range_empty_when_no_match():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")
        await Storage(path).init()
        repo = MetricsRepository(path)
        rows = await repo.range(scope="host", scope_id="missing", metric="cpu_percent",
                                from_ts=0.0, to_ts=1000.0)
        assert rows == []


@pytest.mark.asyncio
async def test_list_events_filters_by_scope_and_kind():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")
        await Storage(path).init()
        repo = MetricsRepository(path)
        await repo.record_event(MetricEvent(ts=100.0, kind="healthcheck_state_change",
                                            scope="component", scope_id="web", payload={"to": "fail"}))
        await repo.record_event(MetricEvent(ts=110.0, kind="apply_completed",
                                            scope="deploy", scope_id="d1", payload={"ok": True}))
        await repo.record_event(MetricEvent(ts=120.0, kind="healthcheck_state_change",
                                            scope="component", scope_id="api", payload={"to": "ok"}))

        all_hc = await repo.list_events(kind="healthcheck_state_change", limit=10)
        assert len(all_hc) == 2
        assert all_hc[0]["scope_id"] in ("web", "api")
        # Newest first
        assert all_hc[0]["ts"] >= all_hc[-1]["ts"]

        web_only = await repo.list_events(scope="component", scope_id="web", limit=10)
        assert len(web_only) == 1
        assert web_only[0]["payload"] == {"to": "fail"}
```

- [ ] **Step 2: Run, verify FAIL**

Run: `cd control-plane && python -m pytest tests/unit/test_storage_metrics.py -v`
Expected: 3 new tests FAIL — methods missing.

- [ ] **Step 3: Append methods to `MetricsRepository`**

In `control-plane/app/storage_metrics.py`, replace the `# range / list_events methods are added in Task 3.` comment with:

```python
    async def range(
        self, *, scope: str, scope_id: str, metric: str,
        from_ts: float, to_ts: float,
    ) -> list[tuple[float, float]]:
        """Return [(ts, value), ...] in ascending ts order, inclusive bounds."""
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT ts, value FROM metric_samples "
                "WHERE scope=? AND scope_id=? AND metric=? AND ts BETWEEN ? AND ? "
                "ORDER BY ts ASC",
                (scope, scope_id, metric, from_ts, to_ts),
            ) as cur:
                rows = await cur.fetchall()
        return [(r[0], r[1]) for r in rows]

    async def list_events(
        self, *, scope: str | None = None, scope_id: str | None = None,
        kind: str | None = None, limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Newest-first list of events; any filter combo is allowed."""
        clauses = []
        params: list[Any] = []
        if scope is not None:
            clauses.append("scope=?")
            params.append(scope)
        if scope_id is not None:
            clauses.append("scope_id=?")
            params.append(scope_id)
        if kind is not None:
            clauses.append("kind=?")
            params.append(kind)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(int(limit))
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT id, ts, kind, scope, scope_id, payload_json "
                "FROM metric_events" + where + " ORDER BY ts DESC LIMIT ?",
                params,
            ) as cur:
                rows = await cur.fetchall()
        return [
            {
                "id": r[0], "ts": r[1], "kind": r[2],
                "scope": r[3], "scope_id": r[4],
                "payload": json.loads(r[5]) if r[5] else None,
            }
            for r in rows
        ]
```

- [ ] **Step 4: Run, verify PASS**

Run: `cd control-plane && python -m pytest tests/unit/test_storage_metrics.py -v`
Expected: all tests PASS (4 + 3 = 7).

- [ ] **Step 5: Commit**

```bash
git add control-plane/app/storage_metrics.py control-plane/tests/unit/test_storage_metrics.py
git commit -m "feat(cp): MetricsRepository range + list_events queries (M2 Task 3)"
```

---

## Task 4: Event payload contract parser

**Files:**
- Create: `control-plane/app/metrics/__init__.py` (empty)
- Create: `control-plane/app/metrics/contract.py`
- Create: `control-plane/tests/unit/test_metrics_contract.py`

- [ ] **Step 1: Write failing test**

Create `control-plane/tests/unit/test_metrics_contract.py`:

```python
from app.metrics.contract import parse_metrics_event, MetricsEvent


def test_parse_full_payload():
    payload = {
        "ts": "2026-04-24T11:34:00Z",
        "host_id": "host1",
        "samples": [
            {"scope": "host", "scope_id": "host1", "metric": "cpu_percent", "value": 42.0},
            {"scope": "component", "scope_id": "web", "metric": "healthcheck_latency_ms", "value": 23.4},
        ],
        "events": [
            {"kind": "healthcheck_state_change", "scope": "component", "scope_id": "web",
             "payload": {"from": "ok", "to": "fail"}},
        ],
    }
    parsed = parse_metrics_event(payload)
    assert isinstance(parsed, MetricsEvent)
    assert parsed.ts > 0
    assert parsed.host_id == "host1"
    assert len(parsed.samples) == 2
    assert parsed.samples[0].metric == "cpu_percent"
    assert parsed.samples[0].value == 42.0
    assert len(parsed.events) == 1
    assert parsed.events[0].kind == "healthcheck_state_change"


def test_parse_drops_unknown_scope_silently():
    payload = {
        "ts": "2026-04-24T11:34:00Z",
        "host_id": "host1",
        "samples": [
            {"scope": "host", "scope_id": "host1", "metric": "cpu_percent", "value": 10},
            {"scope": "WHATEVER", "scope_id": "x", "metric": "y", "value": 1},
        ],
    }
    parsed = parse_metrics_event(payload)
    assert len(parsed.samples) == 1


def test_parse_skips_non_numeric_values():
    payload = {
        "ts": "2026-04-24T11:34:00Z",
        "host_id": "host1",
        "samples": [
            {"scope": "host", "scope_id": "host1", "metric": "cpu_percent", "value": "not a number"},
            {"scope": "host", "scope_id": "host1", "metric": "load1", "value": 1.5},
        ],
    }
    parsed = parse_metrics_event(payload)
    assert len(parsed.samples) == 1
    assert parsed.samples[0].metric == "load1"


def test_parse_missing_ts_uses_now():
    import time
    before = time.time()
    parsed = parse_metrics_event({"host_id": "h", "samples": []})
    assert parsed.ts >= before


def test_parse_missing_host_id_returns_empty_host_id():
    parsed = parse_metrics_event({"samples": []})
    assert parsed.host_id == ""
```

- [ ] **Step 2: Run, verify FAIL**

Run: `cd control-plane && python -m pytest tests/unit/test_metrics_contract.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Create `control-plane/app/metrics/__init__.py`**

```python
```

(empty file — package marker)

- [ ] **Step 4: Create `control-plane/app/metrics/contract.py`**

```python
"""Parser for the event.metrics WS payload."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from ..storage_metrics import MetricSample, MetricEvent


_VALID_SCOPES = {"host", "component", "deploy"}


@dataclass
class MetricsEvent:
    ts: float                  # epoch seconds
    host_id: str
    samples: list[MetricSample] = field(default_factory=list)
    events: list[MetricEvent] = field(default_factory=list)


def _parse_ts(raw: Any) -> float:
    if raw is None:
        return time.time()
    if isinstance(raw, (int, float)):
        return float(raw)
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return time.time()
    return time.time()


def parse_metrics_event(payload: dict[str, Any]) -> MetricsEvent:
    """Permissive parser. Drops malformed entries silently so an evolving
    daemon can add new metrics without crashing the CP."""
    ts = _parse_ts(payload.get("ts"))
    host_id = str(payload.get("host_id", "") or "")

    samples: list[MetricSample] = []
    for s in payload.get("samples") or []:
        try:
            scope = str(s.get("scope", ""))
            if scope not in _VALID_SCOPES:
                continue
            scope_id = str(s.get("scope_id", ""))
            metric = str(s.get("metric", ""))
            if not scope_id or not metric:
                continue
            v = s.get("value")
            if isinstance(v, bool):
                v = 1.0 if v else 0.0
            elif not isinstance(v, (int, float)):
                continue
            samples.append(MetricSample(
                ts=ts, scope=scope, scope_id=scope_id, metric=metric, value=float(v),
            ))
        except (AttributeError, TypeError):
            continue

    events: list[MetricEvent] = []
    for e in payload.get("events") or []:
        try:
            scope = str(e.get("scope", ""))
            if scope not in _VALID_SCOPES:
                continue
            scope_id = str(e.get("scope_id", ""))
            kind = str(e.get("kind", ""))
            if not scope_id or not kind:
                continue
            ev_payload = e.get("payload")
            if ev_payload is not None and not isinstance(ev_payload, dict):
                continue
            events.append(MetricEvent(
                ts=ts, kind=kind, scope=scope, scope_id=scope_id, payload=ev_payload,
            ))
        except (AttributeError, TypeError):
            continue

    return MetricsEvent(ts=ts, host_id=host_id, samples=samples, events=events)
```

- [ ] **Step 5: Run, verify PASS**

Run: `cd control-plane && python -m pytest tests/unit/test_metrics_contract.py -v`
Expected: 5 PASS.

- [ ] **Step 6: Commit**

```bash
git add control-plane/app/metrics/__init__.py control-plane/app/metrics/contract.py control-plane/tests/unit/test_metrics_contract.py
git commit -m "feat(cp): event.metrics payload contract parser (M2 Task 4)"
```

---

## Task 5: Hub event handler — persist incoming metrics

**Files:**
- Create: `control-plane/app/metrics/handler.py`
- Create: `control-plane/tests/unit/test_metrics_handler.py`

- [ ] **Step 1: Write failing test**

```python
import os
import tempfile
import pytest
import aiosqlite

from app.storage import Storage
from app.storage_metrics import MetricsRepository
from app.metrics.handler import make_metrics_event_handler
from app.ws.protocol import make_message, T_EV_METRICS


@pytest.mark.asyncio
async def test_handler_persists_samples_and_events():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")
        await Storage(path).init()
        repo = MetricsRepository(path)

        handler = make_metrics_event_handler(repo)

        msg = make_message(T_EV_METRICS, {
            "ts": "2026-04-24T10:00:00Z",
            "host_id": "host1",
            "samples": [
                {"scope": "host", "scope_id": "host1", "metric": "cpu_percent", "value": 50.5},
                {"scope": "component", "scope_id": "web", "metric": "healthcheck_ok", "value": 1},
            ],
            "events": [
                {"kind": "healthcheck_state_change", "scope": "component", "scope_id": "web",
                 "payload": {"to": "ok"}},
            ],
        })

        await handler("host1", msg)

        async with aiosqlite.connect(path) as db:
            async with db.execute("SELECT COUNT(*) FROM metric_samples") as cur:
                samples_count = (await cur.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM metric_events") as cur:
                events_count = (await cur.fetchone())[0]
        assert samples_count == 2
        assert events_count == 1


@pytest.mark.asyncio
async def test_handler_ignores_non_metrics_messages():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")
        await Storage(path).init()
        repo = MetricsRepository(path)
        handler = make_metrics_event_handler(repo)

        msg = make_message("event.status_change", {"some": "data"})
        await handler("host1", msg)

        async with aiosqlite.connect(path) as db:
            async with db.execute("SELECT COUNT(*) FROM metric_samples") as cur:
                assert (await cur.fetchone())[0] == 0


@pytest.mark.asyncio
async def test_handler_uses_origin_host_id_when_payload_lacks_one():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")
        await Storage(path).init()
        repo = MetricsRepository(path)
        handler = make_metrics_event_handler(repo)

        msg = make_message(T_EV_METRICS, {
            "samples": [
                {"scope": "host", "scope_id": "", "metric": "cpu_percent", "value": 1},
            ],
        })
        # The empty scope_id means the parser drops the sample. But for a host-scoped sample,
        # callers that omit scope_id should default to the WS origin's host_id.
        await handler("originHost", msg)

        async with aiosqlite.connect(path) as db:
            async with db.execute(
                "SELECT scope_id FROM metric_samples WHERE scope='host'"
            ) as cur:
                rows = await cur.fetchall()
        assert rows == [("originHost",)]
```

- [ ] **Step 2: Run, verify FAIL**

Run: `cd control-plane && python -m pytest tests/unit/test_metrics_handler.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Create `control-plane/app/metrics/handler.py`**

```python
"""Hub event handler that persists incoming event.metrics envelopes."""
from __future__ import annotations

from typing import Awaitable, Callable

from ..storage_metrics import MetricsRepository, MetricSample
from ..ws.protocol import Message, T_EV_METRICS
from .contract import parse_metrics_event


EventHandler = Callable[[str, Message], Awaitable[None]]


def make_metrics_event_handler(repo: MetricsRepository) -> EventHandler:
    """Returns a Hub-compatible event handler.

    Side effect: persists samples + events from incoming `event.metrics`
    messages. Other event types pass through unchanged.

    A subtle convenience: for host-scoped samples that omit `scope_id`,
    we substitute the WS origin's `host_id` so daemons can stay terse.
    The contract parser drops samples with empty scope_id; we therefore
    fix them up *before* calling the parser.
    """
    async def handle(host_id: str, msg: Message) -> None:
        if msg.type != T_EV_METRICS:
            return
        payload = dict(msg.payload or {})
        # Default missing host scope_id to the WS origin
        samples_in = payload.get("samples") or []
        fixed_samples = []
        for s in samples_in:
            if isinstance(s, dict) and s.get("scope") == "host" and not s.get("scope_id"):
                s = {**s, "scope_id": host_id}
            fixed_samples.append(s)
        payload["samples"] = fixed_samples
        if not payload.get("host_id"):
            payload["host_id"] = host_id

        ev = parse_metrics_event(payload)
        # Coerce sample.ts from event-level ts (already done in parser),
        # then persist:
        if ev.samples:
            await repo.record_samples(list(ev.samples))
        for me in ev.events:
            await repo.record_event(me)

    return handle
```

- [ ] **Step 4: Run, verify PASS**

Run: `cd control-plane && python -m pytest tests/unit/test_metrics_handler.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add control-plane/app/metrics/handler.py control-plane/tests/unit/test_metrics_handler.py
git commit -m "feat(cp): Hub event handler persists event.metrics envelopes (M2 Task 5)"
```

---

## Task 6: Retention task — rolling cleanup

**Files:**
- Modify: `control-plane/app/storage_metrics.py` — add `cleanup_older_than`
- Create: `control-plane/app/metrics/retention.py` — periodic loop
- Create: `control-plane/tests/unit/test_metrics_retention.py`

- [ ] **Step 1: Write failing test**

Create `control-plane/tests/unit/test_metrics_retention.py`:

```python
import os
import tempfile
import time
import pytest
import aiosqlite

from app.storage import Storage
from app.storage_metrics import MetricsRepository, MetricSample, MetricEvent


@pytest.mark.asyncio
async def test_cleanup_drops_old_samples_and_caps_events():
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")
        await Storage(path).init()
        repo = MetricsRepository(path)

        now = time.time()
        # 5 fresh + 5 stale samples
        await repo.record_samples([
            MetricSample(ts=now - 60, scope="host", scope_id="h1",
                         metric="cpu_percent", value=float(i))
            for i in range(5)
        ] + [
            MetricSample(ts=now - 100_000, scope="host", scope_id="h1",
                         metric="cpu_percent", value=float(i))
            for i in range(5)
        ])
        # 12 events, cap is 10
        for i in range(12):
            await repo.record_event(MetricEvent(
                ts=now - i, kind="apply_completed",
                scope="deploy", scope_id="d1", payload={"i": i},
            ))

        # Retain only last 24h of samples; cap events to last 10
        await repo.cleanup_older_than(samples_max_age_seconds=24 * 3600,
                                      events_keep_last_n=10)

        async with aiosqlite.connect(path) as db:
            async with db.execute("SELECT COUNT(*) FROM metric_samples") as cur:
                assert (await cur.fetchone())[0] == 5
            async with db.execute("SELECT COUNT(*) FROM metric_events") as cur:
                assert (await cur.fetchone())[0] == 10
```

- [ ] **Step 2: Run, verify FAIL**

Run: `cd control-plane && python -m pytest tests/unit/test_metrics_retention.py -v`
Expected: FAIL — `cleanup_older_than` missing.

- [ ] **Step 3: Add `cleanup_older_than` to `MetricsRepository`**

In `control-plane/app/storage_metrics.py`, replace the `# cleanup_older_than is added in Task 6.` comment (renumber later if you wish) with:

```python
    async def cleanup_older_than(
        self, *, samples_max_age_seconds: float, events_keep_last_n: int,
    ) -> None:
        """Drop samples older than `samples_max_age_seconds` from now and
        keep only the most recent `events_keep_last_n` events."""
        import time as _time
        cutoff = _time.time() - samples_max_age_seconds
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "DELETE FROM metric_samples WHERE ts < ?", (cutoff,),
            )
            await db.execute(
                "DELETE FROM metric_events WHERE id NOT IN ("
                "  SELECT id FROM metric_events ORDER BY ts DESC LIMIT ?"
                ")",
                (int(events_keep_last_n),),
            )
            await db.commit()
```

- [ ] **Step 4: Create `control-plane/app/metrics/retention.py`**

```python
"""Background task that periodically prunes old metric samples + events."""
from __future__ import annotations

import asyncio
import logging

from ..storage_metrics import MetricsRepository

log = logging.getLogger("maestro.metrics.retention")


async def retention_loop(
    repo: MetricsRepository,
    *,
    interval_seconds: int = 600,
    samples_max_age_seconds: int = 24 * 3600,
    events_keep_last_n: int = 10_000,
) -> None:
    """Run forever (until cancelled). One pass every `interval_seconds`.

    Defaults: samples retained 24h; events capped at 10k rows.
    """
    while True:
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            return
        try:
            await repo.cleanup_older_than(
                samples_max_age_seconds=samples_max_age_seconds,
                events_keep_last_n=events_keep_last_n,
            )
        except Exception:
            log.exception("retention pass failed")
```

- [ ] **Step 5: Run tests, verify PASS**

Run: `cd control-plane && python -m pytest tests/unit/test_metrics_retention.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add control-plane/app/storage_metrics.py control-plane/app/metrics/retention.py control-plane/tests/unit/test_metrics_retention.py
git commit -m "feat(cp): rolling-window retention for metric samples + events (M2 Task 6)"
```

---

## Task 7: Wire metrics into `main.py` (handler + retention)

**Files:**
- Modify: `control-plane/app/main.py` — instantiate `MetricsRepository`, register handler, start retention task
- Modify: `control-plane/tests/unit/test_storage_metrics.py` — append a smoke test that stands up the app and confirms it doesn't crash

- [ ] **Step 1: Write failing smoke test**

Append to `control-plane/tests/unit/test_storage_metrics.py`:

```python
from fastapi.testclient import TestClient
from app.main import create_app


@pytest.mark.asyncio
async def test_app_lifespan_wires_metrics_state(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("MAESTRO_DB", os.path.join(td, "t.db"))
        # Speed up retention loop in tests; we won't wait for it to fire here.
        monkeypatch.setenv("MAESTRO_METRICS_RETENTION_INTERVAL_S", "60")
        app = create_app()
        with TestClient(app) as _client:
            # State wiring assertions
            repo = app.state.metrics_repo
            assert repo is not None
            # Hub must have at least one event handler registered now
            assert len(app.state.hub._event_handlers) >= 1
```

- [ ] **Step 2: Run, verify FAIL**

Run: `cd control-plane && python -m pytest tests/unit/test_storage_metrics.py::test_app_lifespan_wires_metrics_state -v`
Expected: FAIL — `app.state.metrics_repo` missing.

- [ ] **Step 3: Modify `control-plane/app/main.py`**

Add imports near the existing imports:

```python
from .storage_metrics import MetricsRepository
from .metrics.handler import make_metrics_event_handler
from .metrics.retention import retention_loop
import asyncio
```

Replace the `lifespan` function body with:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = os.environ.get("MAESTRO_DB", "control-plane.db")
    storage = Storage(db_path)
    await storage.init()
    hub = Hub()
    engine = Engine(hub)
    metrics_repo = MetricsRepository(db_path)

    # Persist incoming event.metrics into the metrics store.
    hub.add_event_handler(make_metrics_event_handler(metrics_repo))

    app.state.storage = storage
    app.state.deploy_repo = DeployRepository(db_path)
    app.state.metrics_repo = metrics_repo
    app.state.hub = hub
    app.state.engine = engine

    # Start retention loop in background.
    interval = int(os.environ.get("MAESTRO_METRICS_RETENTION_INTERVAL_S", "600"))
    retention_task = asyncio.create_task(retention_loop(
        metrics_repo, interval_seconds=interval,
    ))

    log.info("control plane ready (db=%s, retention every %ss)", db_path, interval)
    try:
        yield
    finally:
        retention_task.cancel()
        try:
            await retention_task
        except asyncio.CancelledError:
            pass
        log.info("control plane shutting down")
```

- [ ] **Step 4: Run, verify PASS**

Run: `cd control-plane && python -m pytest tests/unit/test_storage_metrics.py -v`
Expected: all PASS.

Run the full suite to make sure nothing regressed:

```
cd control-plane && python -m pytest tests/unit/ -q
```

Expected: 0 failures.

- [ ] **Step 5: Commit**

```bash
git add control-plane/app/main.py control-plane/tests/unit/test_storage_metrics.py
git commit -m "feat(cp): wire MetricsRepository + handler + retention into lifespan (M2 Task 7)"
```

---

## Task 8: REST API — `/api/metrics/*` and `/api/events`

**Files:**
- Create: `control-plane/app/api/metrics.py`
- Modify: `control-plane/app/main.py` — include the new router
- Create: `control-plane/tests/unit/test_api_metrics.py`

- [ ] **Step 1: Write failing tests**

Create `control-plane/tests/unit/test_api_metrics.py`:

```python
import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("MAESTRO_DB", os.path.join(td, "t.db"))
        app = create_app()
        with TestClient(app) as c:
            yield c, app


def test_range_endpoint_returns_empty_when_no_data(client):
    c, _app = client
    r = c.get("/api/metrics/host/h1?metric=cpu_percent&from_ts=0&to_ts=1000")
    assert r.status_code == 200
    assert r.json() == {"scope": "host", "scope_id": "h1",
                        "metric": "cpu_percent", "points": []}


@pytest.mark.asyncio
async def test_range_endpoint_returns_recorded_samples(client):
    c, app = client
    repo = app.state.metrics_repo
    from app.storage_metrics import MetricSample
    await repo.record_samples([
        MetricSample(ts=10.0, scope="host", scope_id="h1", metric="cpu_percent", value=12.0),
        MetricSample(ts=20.0, scope="host", scope_id="h1", metric="cpu_percent", value=24.0),
    ])
    r = c.get("/api/metrics/host/h1?metric=cpu_percent&from_ts=0&to_ts=100")
    assert r.status_code == 200
    body = r.json()
    assert body["points"] == [[10.0, 12.0], [20.0, 24.0]]


@pytest.mark.asyncio
async def test_events_endpoint_filters(client):
    c, app = client
    from app.storage_metrics import MetricEvent
    repo = app.state.metrics_repo
    await repo.record_event(MetricEvent(
        ts=10.0, kind="apply_completed", scope="deploy",
        scope_id="d1", payload={"ok": True},
    ))
    r = c.get("/api/events?scope=deploy&scope_id=d1&kind=apply_completed&limit=5")
    assert r.status_code == 200
    body = r.json()
    assert len(body["events"]) == 1
    assert body["events"][0]["kind"] == "apply_completed"
    assert body["events"][0]["payload"]["ok"] is True


def test_range_rejects_invalid_scope(client):
    c, _app = client
    r = c.get("/api/metrics/banana/h1?metric=x&from_ts=0&to_ts=1")
    assert r.status_code == 400
```

- [ ] **Step 2: Run, verify FAIL**

Run: `cd control-plane && python -m pytest tests/unit/test_api_metrics.py -v`
Expected: FAIL — endpoint missing (404 / module missing).

- [ ] **Step 3: Create `control-plane/app/api/metrics.py`**

```python
"""REST router for time-series metrics + events."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request


router = APIRouter(prefix="/api")


_VALID_SCOPES = {"host", "component", "deploy"}


@router.get("/metrics/{scope}/{scope_id}")
async def get_metric_range(
    request: Request,
    scope: str,
    scope_id: str,
    metric: str = Query(..., min_length=1),
    from_ts: float = Query(...),
    to_ts: float = Query(...),
):
    if scope not in _VALID_SCOPES:
        raise HTTPException(status_code=400, detail=f"invalid scope: {scope}")
    repo = request.app.state.metrics_repo
    rows = await repo.range(
        scope=scope, scope_id=scope_id, metric=metric,
        from_ts=from_ts, to_ts=to_ts,
    )
    return {
        "scope": scope, "scope_id": scope_id, "metric": metric,
        "points": [[t, v] for (t, v) in rows],
    }


@router.get("/events")
async def list_events(
    request: Request,
    scope: str | None = None,
    scope_id: str | None = None,
    kind: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
):
    if scope is not None and scope not in _VALID_SCOPES:
        raise HTTPException(status_code=400, detail=f"invalid scope: {scope}")
    repo = request.app.state.metrics_repo
    events = await repo.list_events(scope=scope, scope_id=scope_id, kind=kind, limit=limit)
    return {"events": events}
```

- [ ] **Step 4: Include router in `main.py`**

In `control-plane/app/main.py`:
- Add to the imports block: `from .api.metrics import router as metrics_router`
- After `app.include_router(deploys_router)`, add: `app.include_router(metrics_router)`

- [ ] **Step 5: Run, verify PASS**

Run: `cd control-plane && python -m pytest tests/unit/test_api_metrics.py -v`
Expected: all 4 PASS.

Then full suite:

```
cd control-plane && python -m pytest tests/unit/ -q
```

Expected: 0 failures.

- [ ] **Step 6: Commit**

```bash
git add control-plane/app/api/metrics.py control-plane/app/main.py control-plane/tests/unit/test_api_metrics.py
git commit -m "feat(cp): /api/metrics/{scope}/{id} and /api/events endpoints (M2 Task 8)"
```

---

## Task 9: End-to-end CP smoke (synthetic event injection)

**Files:**
- Modify: `control-plane/tests/unit/test_metrics_handler.py` — append a higher-level test that simulates a daemon emission via the Hub `_emit` path

This test exercises the Hub → handler → repo path without needing a real daemon. It guarantees that messages routed through the Hub's event fan-out land in the DB.

- [ ] **Step 1: Append failing test**

```python
@pytest.mark.asyncio
async def test_hub_routes_event_metrics_into_repository_via_emit():
    """Simulate a daemon-originated event going through hub._emit()."""
    import os, tempfile
    from app.ws.hub import Hub
    from app.storage import Storage
    from app.storage_metrics import MetricsRepository
    from app.metrics.handler import make_metrics_event_handler
    from app.ws.protocol import make_message, T_EV_METRICS

    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "t.db")
        await Storage(path).init()
        repo = MetricsRepository(path)
        hub = Hub()
        hub.add_event_handler(make_metrics_event_handler(repo))

        msg = make_message(T_EV_METRICS, {
            "ts": "2026-04-24T11:00:00Z",
            "host_id": "host1",
            "samples": [
                {"scope": "host", "scope_id": "host1", "metric": "ram_percent", "value": 73.2},
            ],
        })
        await hub._emit("host1", msg)

        rows = await repo.range(
            scope="host", scope_id="host1", metric="ram_percent",
            from_ts=0, to_ts=99999999999,
        )
        assert len(rows) == 1
        assert rows[0][1] == 73.2
```

- [ ] **Step 2: Run, verify PASS**

Run: `cd control-plane && python -m pytest tests/unit/test_metrics_handler.py -v`
Expected: 4 PASS (3 from Task 5 + 1 new).

- [ ] **Step 3: Commit**

```bash
git add control-plane/tests/unit/test_metrics_handler.py
git commit -m "test(cp): hub fan-out → metrics handler → repo end-to-end (M2 Task 9)"
```

---

## Task 10: Daemon — gopsutil host probe

**Files:**
- Create: `daemon/internal/metrics/host.go`
- Create: `daemon/internal/metrics/host_test.go`
- Modify: `daemon/go.mod`, `daemon/go.sum` — add `github.com/shirou/gopsutil/v3`

- [ ] **Step 1: Create `daemon/internal/metrics/host.go`**

```go
package metrics

import (
	"context"
	"runtime"
	"time"

	"github.com/shirou/gopsutil/v3/cpu"
	"github.com/shirou/gopsutil/v3/load"
	"github.com/shirou/gopsutil/v3/mem"
)

// Sample is the wire format the orchestrator emits for each measurement.
type Sample struct {
	Scope    string  `json:"scope"`
	ScopeID  string  `json:"scope_id"`
	Metric   string  `json:"metric"`
	Value    float64 `json:"value"`
}

// CollectHost returns CPU%, RAM%, and 1-minute load for the local host.
// On platforms where load average is unavailable (Windows), load1 is omitted.
func CollectHost(ctx context.Context) []Sample {
	out := make([]Sample, 0, 3)

	// CPU: 200ms blocking sample. Acceptable inside a 30s ticker.
	cpuCtx, cancel := context.WithTimeout(ctx, 500*time.Millisecond)
	defer cancel()
	if pcts, err := cpu.PercentWithContext(cpuCtx, 200*time.Millisecond, false); err == nil && len(pcts) > 0 {
		out = append(out, Sample{Scope: "host", Metric: "cpu_percent", Value: pcts[0]})
	}

	if vm, err := mem.VirtualMemory(); err == nil {
		out = append(out, Sample{Scope: "host", Metric: "ram_percent", Value: vm.UsedPercent})
	}

	if runtime.GOOS != "windows" {
		if l, err := load.Avg(); err == nil {
			out = append(out, Sample{Scope: "host", Metric: "load1", Value: l.Load1})
		}
	}
	return out
}
```

- [ ] **Step 2: Create `daemon/internal/metrics/host_test.go`**

```go
package metrics

import (
	"context"
	"testing"
)

func TestCollectHostReturnsAtLeastOneSample(t *testing.T) {
	samples := CollectHost(context.Background())
	if len(samples) == 0 {
		t.Fatalf("expected at least one host sample, got 0")
	}
	for _, s := range samples {
		if s.Scope != "host" {
			t.Errorf("expected scope=host, got %q", s.Scope)
		}
		if s.Metric == "" {
			t.Error("metric name must be non-empty")
		}
	}
}
```

- [ ] **Step 3: Add gopsutil dep**

```
cd daemon && go get github.com/shirou/gopsutil/v3@latest
```

- [ ] **Step 4: Run the test**

```
cd daemon && go test ./internal/metrics/...
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add daemon/internal/metrics/host.go daemon/internal/metrics/host_test.go daemon/go.mod daemon/go.sum
git commit -m "feat(daemon): host CPU/RAM/load probe via gopsutil (M2 Task 10)"
```

---

## Task 11: Daemon — emit v1-shaped event.metrics

**Files:**
- Modify: `daemon/internal/orchestrator/orchestrator.go` — `PublishMetrics` body

- [ ] **Step 1: Replace `PublishMetrics`**

Open `daemon/internal/orchestrator/orchestrator.go`, locate `func (o *Orchestrator) PublishMetrics(...)` (around line 401), and replace its body with:

```go
func (o *Orchestrator) PublishMetrics(ctx context.Context, client *ws.Client) error {
	comps, err := o.Store.List(ctx)
	if err != nil {
		return err
	}

	samples := []map[string]any{}

	// Host samples. We leave scope_id empty: the CP defaults it to the
	// daemon's host_id (resolved from the WS origin), so the daemon
	// doesn't need to know its own host_id here.
	for _, hs := range metrics.CollectHost(ctx) {
		samples = append(samples, map[string]any{
			"scope":    "host",
			"scope_id": "",
			"metric":   hs.Metric,
			"value":    hs.Value,
		})
	}

	// Per-component healthcheck samples.
	for _, c := range comps {
		// Liveness: 1 if last healthcheck OK, 0 if last failed, omitted if unknown.
		if c.LastHCAt != nil {
			v := 0.0
			if c.LastHCOK {
				v = 1.0
			}
			samples = append(samples, map[string]any{
				"scope":    "component",
				"scope_id": c.ID,
				"metric":   "healthcheck_ok",
				"value":    v,
			})
		}
	}

	// Note: host_id is intentionally omitted from the payload. The CP's
	// metrics handler fills it in from the WS connection's registered
	// host_id (see Task 5). This keeps the daemon stateless w.r.t. its
	// own identity at the orchestrator layer.
	payload := map[string]any{
		"ts":      time.Now().UTC().Format(time.RFC3339),
		"samples": samples,
	}
	return client.SendEvent(ws.TypeEventMetrics, payload)
}
```

Add the import at the top of the file (the existing import block):

```go
"github.com/maestro-project/maestro-daemon/internal/metrics"
```

- [ ] **Step 2: Build the daemon**

```
cd daemon && go build ./...
```

Expected: success. Fix any compilation error inline (most likely the `HostID` accessor name).

- [ ] **Step 3: Run the daemon test suite**

```
cd daemon && go test ./...
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add daemon/internal/orchestrator/orchestrator.go
git commit -m "feat(daemon): PublishMetrics emits v1 payload with host + healthcheck samples (M2 Task 11)"
```

---

## Task 12: End-to-end smoke

**Files:** none changed — exercise the running CP.

This is a manual / scripted smoke. Focus: prove that records from a synthetic POST land in `/api/metrics/*` and that the retention loop exists.

- [ ] **Step 1: Run full unit suite**

```
cd "/c/Users/navis/Documents/Claude/Projects/Remote Control Agent/control-plane" && python -m pytest tests/unit/ -q
```

Expected: 0 failures.

- [ ] **Step 2: Start CP and inject a synthetic metrics event via the Hub directly (no daemon)**

The Hub doesn't expose an HTTP endpoint to inject events from outside, so we use a small inline Python script for the smoke. Save as `/tmp/m2-smoke.py`:

```python
import asyncio, os, time

os.environ.setdefault("MAESTRO_DB", "/tmp/m2-smoke.db")

import importlib, urllib.request, json

async def main():
    # Boot the app's lifespan in-process.
    from app.main import create_app
    from app.ws.protocol import make_message, T_EV_METRICS
    app = create_app()

    # FastAPI lifespan must be entered manually for an out-of-server smoke.
    async with app.router.lifespan_context(app):
        msg = make_message(T_EV_METRICS, {
            "ts": "2026-04-24T12:00:00Z",
            "host_id": "host1",
            "samples": [
                {"scope": "host",      "scope_id": "host1", "metric": "cpu_percent", "value": 33.3},
                {"scope": "host",      "scope_id": "host1", "metric": "ram_percent", "value": 64.0},
                {"scope": "component", "scope_id": "web",   "metric": "healthcheck_ok", "value": 1},
            ],
        })
        await app.state.hub._emit("host1", msg)
        rows = await app.state.metrics_repo.range(
            scope="host", scope_id="host1", metric="cpu_percent",
            from_ts=0, to_ts=time.time() + 1,
        )
        print("host cpu_percent samples:", rows)
        events = await app.state.metrics_repo.list_events(limit=10)
        print("events:", events)

asyncio.run(main())
```

Run from the repo root:

```
cd "/c/Users/navis/Documents/Claude/Projects/Remote Control Agent" && \
  PYTHONPATH=control-plane control-plane/.venv/Scripts/python.exe /tmp/m2-smoke.py
```

Expected output:
- `host cpu_percent samples: [(<ts>, 33.3)]`
- `events: []`

- [ ] **Step 3: Document the new env var in CP README**

Append to `control-plane/README.md` (or to a new `docs/` snippet):

```
- `MAESTRO_METRICS_RETENTION_INTERVAL_S` — seconds between metric retention sweeps (default 600)
```

- [ ] **Step 4: Final commit**

```bash
git add control-plane/README.md
git commit -m "docs(cp): document MAESTRO_METRICS_RETENTION_INTERVAL_S (M2 Task 12)"
```

---

## Milestone Exit Criteria

All of the following must hold:

1. `pytest control-plane/tests/unit/ -q` is green.
2. `go test ./...` from `daemon/` is green.
3. The CP starts cleanly with the new env var, registers the metrics handler with the Hub, and starts the retention task.
4. `GET /api/metrics/host/<id>?metric=cpu_percent&from_ts=…&to_ts=…` returns time-series data after a synthetic injection.
5. `GET /api/events?scope=…` returns recorded events.
6. The daemon, when run locally with a CP attached, emits the v1 payload (host CPU/RAM/load + per-component healthcheck) without crashing.

Out of scope (deferred):
- `/ws/ui` browser fan-out (M2.5).
- Per-container Docker stats (M2.6).
- Custom `/metrics` Prometheus scraping (M2.6).
- Frontend integration of live charts (M2.5/M4 follow-up).
