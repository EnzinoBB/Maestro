import os
import tempfile
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.wizard.docker_inspect import DockerSuggestions


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


def test_inspect_returns_400_on_missing_image(client):
    r = client.post("/api/wizard/docker/inspect", json={})
    assert r.status_code == 400


async def _fake_inspect(image, tag, *, pull_first=True):
    return DockerSuggestions(
        exposed_ports=[80, 443],
        env=[{"key": "NGINX_VERSION", "value": "1.25.0"}],
        volumes=["/var/cache/nginx"],
    )


def test_inspect_returns_suggestions(client):
    with patch("app.api.wizard.inspect_image", new=_fake_inspect):
        r = client.post("/api/wizard/docker/inspect",
                        json={"image": "nginx", "tag": "1.25"})
    assert r.status_code == 200
    body = r.json()
    assert body["exposed_ports"] == [80, 443]
    assert body["env"] == [{"key": "NGINX_VERSION", "value": "1.25.0"}]
    assert body["volumes"] == ["/var/cache/nginx"]


async def _empty_inspect(image, tag, *, pull_first=True):
    return DockerSuggestions()


def test_inspect_returns_empty_suggestions_gracefully(client):
    with patch("app.api.wizard.inspect_image", new=_empty_inspect):
        r = client.post("/api/wizard/docker/inspect",
                        json={"image": "private/nope", "tag": "latest"})
    assert r.status_code == 200
    body = r.json()
    assert body == {"exposed_ports": [], "env": [], "volumes": []}
