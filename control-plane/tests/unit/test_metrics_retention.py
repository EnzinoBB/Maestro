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

        await repo.cleanup_older_than(samples_max_age_seconds=24 * 3600,
                                      events_keep_last_n=10)

        async with aiosqlite.connect(path) as db:
            async with db.execute("SELECT COUNT(*) FROM metric_samples") as cur:
                assert (await cur.fetchone())[0] == 5
            async with db.execute("SELECT COUNT(*) FROM metric_events") as cur:
                assert (await cur.fetchone())[0] == 10
