from pathlib import Path
import tempfile
import os

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("RCA_DB", os.path.join(td, "t.db"))
        app = create_app()
        with TestClient(app) as c:
            yield c


FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures"


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_validate_simple(client):
    body = (FIXTURES / "deployment-simple.yaml").read_text()
    r = client.post("/api/config/validate", content=body, headers={"content-type": "text/yaml"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert "web" in r.json()["components"]


def test_validate_bad_cycle(client):
    body = (FIXTURES / "bad-cycle.yaml").read_text()
    r = client.post("/api/config/validate", content=body, headers={"content-type": "text/yaml"})
    assert r.status_code == 400


def test_apply_without_daemon_skips_with_error(client):
    """With no daemon connected, apply should render the diff as all 'create'
    but fail on send (DaemonOffline) since the host is not online."""
    body = (FIXTURES / "deployment-simple.yaml").read_text()
    r = client.post("/api/config/apply", content=body, headers={"content-type": "text/yaml"})
    # Endpoint always returns 200 with the result object; ok=False is acceptable
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is False
    assert data.get("error")


def test_hosts_empty(client):
    r = client.get("/api/hosts")
    assert r.status_code == 200
    assert r.json()["hosts"] == []


def test_dry_run_apply(client):
    body = (FIXTURES / "deployment-simple.yaml").read_text()
    r = client.post("/api/config/apply?dry_run=true", content=body,
                    headers={"content-type": "text/yaml"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["diff"] is not None
    assert len(data["diff"]["changes"]) == 1  # 'web'
