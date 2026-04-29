import base64
import hashlib
import io
import os
import tarfile
import tempfile
import pytest
from fastapi.testclient import TestClient
from app.config.loader import parse_deployment
from app.config.renderer import render_component
from app.main import create_app


_YAML_FILES_STORE = """
api_version: maestro/v1
project: t
hosts:
  h: {type: linux, address: 1.2.3.4}
components:
  c:
    source: {type: docker, image: nginx}
    run: {type: docker}
    config:
      files:
        - source: site
          dest: /var/www/site
          strategy: atomic_symlink
deployment:
  - host: h
    components: [c]
"""


def _tar_of(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data in sorted(files.items()):
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mtime = 0
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


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


def test_apply_accepts_files_store_in_body(client):
    """HTTP 200 is returned and the diff reflects the archive from files_store."""
    tar_bytes = _tar_of({"index.html": b"<h1>x</h1>"})
    tar_b64 = base64.b64encode(tar_bytes).decode()
    body = {
        "yaml_text": _YAML_FILES_STORE,
        "files_store": {"site": tar_b64},
    }
    # dry-run so we don't need daemon connection
    r = client.post("/api/config/apply?dry_run=true", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("ok") is not False
    # dry_run returns a diff; the component must appear as "create" (no daemon)
    changes = data["diff"]["changes"]
    assert len(changes) == 1
    assert changes[0]["action"] == "create"
    assert changes[0]["component_id"] == "c"
    assert changes[0]["new_hash"] is not None


def test_files_store_content_reaches_renderer():
    """render_component with files_store produces the correct archive bytes/hash."""
    tar_bytes = _tar_of({"index.html": b"<h1>hello</h1>"})
    tar_b64 = base64.b64encode(tar_bytes).decode()
    expected_hash = hashlib.sha256(tar_bytes).hexdigest()

    spec = parse_deployment(_YAML_FILES_STORE)
    rc = render_component(spec, "c", "h", files_store={"site": tar_b64})

    archives = rc.config_archives
    assert len(archives) == 1
    a = archives[0]
    assert a.tar_bytes == tar_bytes, "renderer must pass through the store bytes unchanged"
    assert a.content_hash == expected_hash, "content_hash must match sha256 of the tar bytes"
    assert a.dest == "/var/www/site"
    assert a.strategy == "atomic_symlink"


def test_apply_rejects_non_string_files_store_value(client):
    """files_store with an integer value must return HTTP 400 naming the key."""
    body = {
        "yaml_text": _YAML_FILES_STORE,
        "files_store": {"site": 123},
    }
    r = client.post("/api/config/apply?dry_run=true", json=body)
    assert r.status_code == 400, r.text
    resp = r.json()
    assert resp["ok"] is False
    assert resp["error"]["code"] == "bad_request"
    message = resp["error"]["message"]
    assert "files_store" in message
    assert "site" in message
    assert "int" in message
