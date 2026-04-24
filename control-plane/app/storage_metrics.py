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

    # ---------- reads ----------

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

    # ---------- maintenance (Task 6) ----------
    # cleanup_older_than is added in Task 6.
