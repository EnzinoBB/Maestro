import base64
import io
import tarfile
from app.config.loader import parse_deployment
from app.config.renderer import render_component


def _make_yaml(source_path: str) -> str:
    return f"""
api_version: maestro/v1
project: t
hosts:
  h: {{type: linux, address: 1.2.3.4}}
components:
  c:
    source: {{type: docker, image: nginx}}
    run: {{type: docker}}
    config:
      files:
        - source: {source_path}
          dest: /var/www/site
          strategy: atomic_symlink
          mode: 0755
deployment:
  - host: h
    components: [c]
"""


def test_render_bundles_directory_to_tar_archive(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<h1>hi</h1>")
    (site / "style.css").write_text("body{}")

    spec = parse_deployment(_make_yaml(str(site)))
    rc = render_component(spec, "c", "h")
    archives = rc.to_payload()["config_archives"]
    assert len(archives) == 1
    a = archives[0]
    assert a["dest"] == "/var/www/site"
    assert a["strategy"] == "atomic_symlink"
    assert a["mode"] == 0o755
    # tar_b64 decodes to a valid tar with both files
    data = base64.b64decode(a["tar_b64"])
    tf = tarfile.open(fileobj=io.BytesIO(data), mode="r")
    names = sorted(m.name for m in tf.getmembers() if m.isfile())
    assert names == ["index.html", "style.css"]
    # content_hash is a stable sha256 hex digest
    assert len(a["content_hash"]) == 64
    assert all(c in "0123456789abcdef" for c in a["content_hash"])


def test_render_hash_deterministic_across_calls(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<h1>hi</h1>")

    spec = parse_deployment(_make_yaml(str(site)))
    rc1 = render_component(spec, "c", "h")
    rc2 = render_component(spec, "c", "h")
    h1 = rc1.to_payload()["config_archives"][0]["content_hash"]
    h2 = rc2.to_payload()["config_archives"][0]["content_hash"]
    assert h1 == h2


def test_render_hash_changes_when_content_changes(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<h1>v1</h1>")

    spec = parse_deployment(_make_yaml(str(site)))
    h1 = render_component(spec, "c", "h").to_payload()["config_archives"][0]["content_hash"]

    (site / "index.html").write_text("<h1>v2</h1>")
    h2 = render_component(spec, "c", "h").to_payload()["config_archives"][0]["content_hash"]
    assert h1 != h2
