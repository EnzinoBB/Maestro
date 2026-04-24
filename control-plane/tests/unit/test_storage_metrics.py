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
