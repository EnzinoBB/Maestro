"""Time-series and event store backed by SQLite (rolling window)."""
from __future__ import annotations

import aiosqlite
import json
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

    # ---------- maintenance (Task 6) ----------
    # cleanup_older_than is added in Task 6.
