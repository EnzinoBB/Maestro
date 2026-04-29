import os

from app.mcp.server import _auth_headers


def test_auth_headers_includes_bearer_when_env_set(monkeypatch):
    monkeypatch.setenv("MAESTRO_API_KEY", "mae_test_xyz")
    assert _auth_headers() == {"Authorization": "Bearer mae_test_xyz"}


def test_auth_headers_empty_when_env_unset(monkeypatch):
    monkeypatch.delenv("MAESTRO_API_KEY", raising=False)
    assert _auth_headers() == {}


def test_auth_headers_empty_when_env_blank(monkeypatch):
    monkeypatch.setenv("MAESTRO_API_KEY", "")
    assert _auth_headers() == {}
