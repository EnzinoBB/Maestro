import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client_singleuser(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("MAESTRO_DB", os.path.join(td, "t.db"))
        monkeypatch.setenv("MAESTRO_METRICS_RETENTION_INTERVAL_S", "3600")
        monkeypatch.delenv("MAESTRO_SINGLE_USER_MODE", raising=False)
        # Pin a known token so the assertion is exact.
        monkeypatch.setenv("MAESTRO_DAEMON_TOKEN", "test-token-xyz")
        app = create_app()
        with TestClient(app) as c:
            yield c


@pytest.fixture
def client_multiuser_anon(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("MAESTRO_DB", os.path.join(td, "t.db"))
        monkeypatch.setenv("MAESTRO_METRICS_RETENTION_INTERVAL_S", "3600")
        monkeypatch.setenv("MAESTRO_SINGLE_USER_MODE", "false")
        monkeypatch.setenv("MAESTRO_DAEMON_TOKEN", "test-token-xyz")
        app = create_app()
        with TestClient(app) as c:
            yield c


def test_singleuser_admin_can_fetch_enroll_payload(client_singleuser):
    r = client_singleuser.get("/api/admin/daemon-enroll")
    assert r.status_code == 200
    body = r.json()
    assert body["token"] == "test-token-xyz"
    assert body["token_available"] is True
    assert body["cp_url"].startswith("http://")
    assert body["install_url"].endswith("/install-daemon.sh")


def test_anonymous_in_multiuser_cannot_fetch_enroll(client_multiuser_anon):
    r = client_multiuser_anon.get("/api/admin/daemon-enroll")
    assert r.status_code == 401


def test_public_url_env_overrides_request_host(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("MAESTRO_DB", os.path.join(td, "t.db"))
        monkeypatch.setenv("MAESTRO_METRICS_RETENTION_INTERVAL_S", "3600")
        monkeypatch.setenv("MAESTRO_DAEMON_TOKEN", "abc")
        monkeypatch.setenv("MAESTRO_PUBLIC_URL", "https://cp.example.org/")
        app = create_app()
        with TestClient(app) as c:
            r = c.get("/api/admin/daemon-enroll")
        assert r.status_code == 200
        body = r.json()
        # Trailing slash stripped
        assert body["cp_url"] == "https://cp.example.org"


def test_no_token_when_neither_env_nor_file_present(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("MAESTRO_DB", os.path.join(td, "t.db"))
        monkeypatch.setenv("MAESTRO_METRICS_RETENTION_INTERVAL_S", "3600")
        monkeypatch.delenv("MAESTRO_DAEMON_TOKEN", raising=False)
        monkeypatch.setenv("MAESTRO_TOKEN_FILE", os.path.join(td, "no-such-file"))
        app = create_app()
        with TestClient(app) as c:
            r = c.get("/api/admin/daemon-enroll")
        assert r.status_code == 200
        body = r.json()
        assert body["token"] == ""
        assert body["token_available"] is False
