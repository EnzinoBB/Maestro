import os

from app.mcp.server import _auth_headers, _schema_apply_config


def test_auth_headers_includes_bearer_when_env_set(monkeypatch):
    monkeypatch.setenv("MAESTRO_API_KEY", "mae_test_xyz")
    assert _auth_headers() == {"Authorization": "Bearer mae_test_xyz"}


def test_auth_headers_empty_when_env_unset(monkeypatch):
    monkeypatch.delenv("MAESTRO_API_KEY", raising=False)
    assert _auth_headers() == {}


def test_auth_headers_empty_when_env_blank(monkeypatch):
    monkeypatch.setenv("MAESTRO_API_KEY", "")
    assert _auth_headers() == {}


def test_apply_config_schema_exposes_yaml_dry_run_template_files():
    schema = _schema_apply_config()
    assert schema["type"] == "object"
    props = schema["properties"]
    assert set(props.keys()) == {
        "yaml_text", "dry_run", "template_store", "files_store",
    }
    assert schema["required"] == ["yaml_text"]
    # Stores accept arbitrary string-keyed string values (template content
    # for templates, base64-encoded tar bytes for files).
    for store in ("template_store", "files_store"):
        assert props[store]["type"] == "object"
        assert props[store]["additionalProperties"] == {"type": "string"}
