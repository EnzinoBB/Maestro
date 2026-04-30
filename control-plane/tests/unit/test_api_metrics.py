import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("MAESTRO_DB", os.path.join(td, "t.db"))
        monkeypatch.setenv("MAESTRO_METRICS_RETENTION_INTERVAL_S", "3600")
        app = create_app()
        with TestClient(app) as c:
            # Setup admin
            r = c.post("/api/auth/setup-admin",
                       json={"username": "admin", "password": "correct-horse"})
            assert r.status_code == 200
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
