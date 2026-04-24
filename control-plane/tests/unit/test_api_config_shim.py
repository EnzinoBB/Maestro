from pathlib import Path
import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from app.main import create_app

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures"


@pytest.fixture
def client(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("MAESTRO_DB", os.path.join(td, "t.db"))
        app = create_app()
        with TestClient(app) as c:
            yield c


def test_config_apply_creates_default_deploy_with_version(client):
    body = (FIXTURES / "deployment-simple.yaml").read_text()
    r = client.post("/api/config/apply", content=body,
                    headers={"content-type": "text/yaml"})
    assert r.status_code == 200

    r = client.get("/api/deploys")
    deploys = r.json()["deploys"]
    default = next((d for d in deploys if d["name"] == "default"), None)
    assert default is not None
    assert default["current_version"] == 1


def test_config_apply_second_time_appends_version(client):
    body = (FIXTURES / "deployment-simple.yaml").read_text()
    client.post("/api/config/apply", content=body, headers={"content-type": "text/yaml"})
    client.post("/api/config/apply", content=body, headers={"content-type": "text/yaml"})

    r = client.get("/api/deploys")
    default = next(d for d in r.json()["deploys"] if d["name"] == "default")
    r = client.get(f"/api/deploys/{default['id']}")
    assert len(r.json()["versions"]) == 2


def test_config_get_returns_latest_default_version(client):
    body = (FIXTURES / "deployment-simple.yaml").read_text()
    client.post("/api/config/apply", content=body, headers={"content-type": "text/yaml"})
    r = client.get("/api/config")
    assert r.status_code == 200
    data = r.json()
    assert data["yaml_text"] is not None
    assert "web" in data["yaml_text"]
