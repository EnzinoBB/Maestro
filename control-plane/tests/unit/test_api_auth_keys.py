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
        monkeypatch.setenv("MAESTRO_SINGLE_USER_MODE", "false")
        app = create_app()
        with TestClient(app) as c:
            r = c.post("/api/auth/setup-admin",
                       json={"username": "alice", "password": "correct-horse"})
            assert r.status_code == 200
            yield c


def test_post_keys_creates_and_returns_clear_key(client):
    r = client.post("/api/auth/keys", json={"label": "laptop"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["label"] == "laptop"
    assert body["key"].startswith("mae_")
    assert len(body["key"]) >= 40
    assert body["prefix"] == body["key"][:9]
    assert "warning" in body


def test_post_keys_rejects_empty_label(client):
    r = client.post("/api/auth/keys", json={"label": ""})
    assert r.status_code == 400


def test_post_keys_rejects_label_over_64_chars(client):
    r = client.post("/api/auth/keys", json={"label": "x" * 65})
    assert r.status_code == 400


def test_post_keys_rejects_duplicate_active_label(client):
    r = client.post("/api/auth/keys", json={"label": "laptop"})
    assert r.status_code == 201
    r = client.post("/api/auth/keys", json={"label": "laptop"})
    assert r.status_code == 409


def test_post_keys_enforces_max_active_keys(client):
    for i in range(10):
        r = client.post("/api/auth/keys", json={"label": f"k{i}"})
        assert r.status_code == 201, r.text
    r = client.post("/api/auth/keys", json={"label": "k10"})
    assert r.status_code == 409
    body = r.json()
    assert body["error"]["code"] == "conflict"


def test_post_keys_requires_auth(client):
    client.cookies.clear()
    r = client.post("/api/auth/keys", json={"label": "laptop"})
    assert r.status_code == 401
