import base64
import io
import tarfile
from fastapi.testclient import TestClient
from app.main import app


def _tar_of(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, data in sorted(files.items()):
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mtime = 0
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_apply_accepts_files_store_in_body():
    yaml_text = """
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
    tar_b64 = base64.b64encode(_tar_of({"index.html": b"<h1>x</h1>"})).decode()
    body = {
        "yaml_text": yaml_text,
        "files_store": {"site": tar_b64},
    }
    with TestClient(app) as client:
        # dry-run so we don't need daemon connection
        r = client.post("/api/config/apply?dry_run=true", json=body)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("ok") is not False
