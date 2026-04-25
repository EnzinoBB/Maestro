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
async def test_hub_routes_event_metrics_into_repository_via_emit():
    """Simulate a daemon-originated event going through hub._emit()."""
    from app.ws.hub import Hub

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
        await handler("originHost", msg)

        async with aiosqlite.connect(path) as db:
            async with db.execute(
                "SELECT scope_id FROM metric_samples WHERE scope='host'"
            ) as cur:
                rows = await cur.fetchall()
        assert rows == [("originHost",)]
