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
        monkeypatch.setenv("MAESTRO_METRICS_RETENTION_INTERVAL_S", "3600")
        app = create_app()
        with TestClient(app) as c:
            # Setup admin
            r = c.post("/api/auth/setup-admin",
                       json={"username": "admin", "password": "correct-horse"})
            assert r.status_code == 200
            yield c


def test_list_empty(client):
    r = client.get("/api/deploys")
    assert r.status_code == 200
    assert r.json() == {"deploys": []}


def test_create_list_get_delete_cycle(client):
    r = client.post("/api/deploys", json={"name": "webapp-prod"})
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["name"] == "webapp-prod"
    # owner_user_id should be the admin user created by the fixture
    assert created["owner_user_id"] is not None
    assert created["current_version"] is None
    deploy_id = created["id"]

    r = client.get("/api/deploys")
    assert r.status_code == 200
    assert len(r.json()["deploys"]) == 1

    r = client.get(f"/api/deploys/{deploy_id}")
    assert r.status_code == 200
    assert r.json()["id"] == deploy_id
    assert r.json()["versions"] == []

    r = client.delete(f"/api/deploys/{deploy_id}")
    assert r.status_code == 204

    r = client.get(f"/api/deploys/{deploy_id}")
    assert r.status_code == 404


def test_list_deploys_projects_latest_version(client):
    # Empty deploy: latest_version is null
    r = client.post("/api/deploys", json={"name": "fresh"})
    assert r.status_code == 201
    fresh_id = r.json()["id"]
    assert r.json()["latest_version"] is None

    # Apply a version, then list — latest_version reflects the apply result
    client.post(f"/api/deploys/{fresh_id}/apply", json={"yaml_text": _YAML})

    r = client.get("/api/deploys")
    assert r.status_code == 200
    deploys = r.json()["deploys"]
    fresh = next(d for d in deploys if d["id"] == fresh_id)
    assert fresh["current_version"] == 1
    lv = fresh["latest_version"]
    assert lv is not None
    assert lv["version_n"] == 1
    assert lv["kind"] == "apply"
    # result_json.ok is False here because no daemon is connected, but the
    # important thing is that the projection is populated and not "unknown".
    assert isinstance(lv["result_json"], dict)
    assert "ok" in lv["result_json"]
    # Attributed to the calling user (admin from the fixture).
    assert isinstance(lv["applied_by_user_id"], str)
    assert lv["applied_by_user_id"] != "singleuser"


def test_get_deploy_includes_latest_version(client):
    r = client.post("/api/deploys", json={"name": "g"})
    deploy_id = r.json()["id"]
    client.post(f"/api/deploys/{deploy_id}/apply", json={"yaml_text": _YAML})

    r = client.get(f"/api/deploys/{deploy_id}")
    body = r.json()
    assert body["latest_version"] is not None
    assert body["latest_version"]["version_n"] == body["current_version"]


def test_create_duplicate_name_is_409(client):
    client.post("/api/deploys", json={"name": "x"})
    r = client.post("/api/deploys", json={"name": "x"})
    assert r.status_code == 409


def test_create_missing_name_is_400(client):
    r = client.post("/api/deploys", json={})
    assert r.status_code == 400


_YAML = (FIXTURES / "deployment-simple.yaml").read_text()


def test_apply_creates_version_when_dry_run_false_even_if_no_daemon(client):
    r = client.post("/api/deploys", json={"name": "app"})
    deploy_id = r.json()["id"]

    r = client.post(
        f"/api/deploys/{deploy_id}/apply",
        json={"yaml_text": _YAML},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["version_n"] == 1
    assert data["kind"] == "apply"

    r = client.get(f"/api/deploys/{deploy_id}")
    assert r.json()["current_version"] == 1
    assert len(r.json()["versions"]) == 1


def test_apply_dry_run_does_not_create_version(client):
    r = client.post("/api/deploys", json={"name": "app"})
    deploy_id = r.json()["id"]

    r = client.post(
        f"/api/deploys/{deploy_id}/apply?dry_run=true",
        json={"yaml_text": _YAML},
    )
    assert r.status_code == 200
    data = r.json()
    assert "diff" in data
    assert "version_n" not in data

    r = client.get(f"/api/deploys/{deploy_id}")
    assert r.json()["current_version"] is None


def test_apply_to_unknown_deploy_is_404(client):
    r = client.post(
        "/api/deploys/does-not-exist/apply",
        json={"yaml_text": _YAML},
    )
    assert r.status_code == 404


def test_apply_invalid_yaml_is_400(client):
    r = client.post("/api/deploys", json={"name": "app"})
    deploy_id = r.json()["id"]
    r = client.post(f"/api/deploys/{deploy_id}/apply", json={"yaml_text": "this: is: not valid"})
    assert r.status_code == 400


def test_validate_on_deploy(client):
    r = client.post("/api/deploys", json={"name": "app"})
    deploy_id = r.json()["id"]
    r = client.post(f"/api/deploys/{deploy_id}/validate", json={"yaml_text": _YAML})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_diff_on_deploy(client):
    r = client.post("/api/deploys", json={"name": "app"})
    deploy_id = r.json()["id"]
    r = client.post(f"/api/deploys/{deploy_id}/diff", json={"yaml_text": _YAML})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert "diff" in r.json()


def test_rollback_creates_new_version_pointing_at_target(client):
    r = client.post("/api/deploys", json={"name": "app"})
    deploy_id = r.json()["id"]

    client.post(f"/api/deploys/{deploy_id}/apply", json={"yaml_text": _YAML})
    client.post(f"/api/deploys/{deploy_id}/apply", json={"yaml_text": _YAML})

    r = client.post(f"/api/deploys/{deploy_id}/rollback/1")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["version_n"] == 3
    assert data["kind"] == "rollback"

    r = client.get(f"/api/deploys/{deploy_id}")
    versions = r.json()["versions"]
    v1 = next(v for v in versions if v["version_n"] == 1)
    v3 = next(v for v in versions if v["version_n"] == 3)
    assert v3["parent_version_id"] == v1["id"]
    assert v3["yaml_text"] == v1["yaml_text"]


def test_rollback_to_unknown_version_is_404(client):
    r = client.post("/api/deploys", json={"name": "app"})
    deploy_id = r.json()["id"]
    client.post(f"/api/deploys/{deploy_id}/apply", json={"yaml_text": _YAML})
    r = client.post(f"/api/deploys/{deploy_id}/rollback/99")
    assert r.status_code == 404


def test_cross_deploy_port_collision_is_409(client):
    yaml1 = """api_version: maestro/v1
project: a
hosts:
  h1: {type: linux, address: 1.2.3.4}
components:
  web:
    source: {type: docker, image: nginx}
    run:
      type: docker
      ports: ["80:80"]
deployment:
  - host: h1
    components: [web]
"""
    yaml2 = """api_version: maestro/v1
project: b
hosts:
  h1: {type: linux, address: 1.2.3.4}
components:
  api:
    source: {type: docker, image: httpd}
    run:
      type: docker
      ports: ["80:8080"]
deployment:
  - host: h1
    components: [api]
"""
    r = client.post("/api/deploys", json={"name": "one"})
    d1 = r.json()["id"]
    r = client.post("/api/deploys", json={"name": "two"})
    d2 = r.json()["id"]

    client.post(f"/api/deploys/{d1}/apply", json={"yaml_text": yaml1})
    r = client.post(f"/api/deploys/{d2}/apply", json={"yaml_text": yaml2})
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "conflict"
    assert "message" in body["error"]
    assert "conflicts" in body["error"]
    assert body["error"]["conflicts"][0]["kind"] == "host_port_collision"
    assert body["error"]["conflicts"][0]["host_port"] == 80
