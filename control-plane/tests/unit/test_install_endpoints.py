"""Tests for /install-daemon.sh and /dist/* endpoints (Layer 1)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def dist_fixture(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "maestrod-linux-amd64").write_bytes(b"FAKE_BINARY_AMD64")
    (dist / "maestrod-linux-arm64").write_bytes(b"FAKE_BINARY_ARM64")
    (dist / "SHA256SUMS").write_text(
        "aaa  maestrod-linux-amd64\nbbb  maestrod-linux-arm64\n"
    )

    script = tmp_path / "install-daemon.sh"
    script.write_text("#!/usr/bin/env bash\nDEFAULT_CP_URL=\"\"\necho hi\n")

    monkeypatch.setenv("MAESTRO_DIST_DIR", str(dist))
    monkeypatch.setenv("MAESTRO_INSTALL_SCRIPT", str(script))
    return dist, script


def _app(_fixture):
    return create_app()


def test_dist_serves_binary(dist_fixture):
    client = TestClient(_app(dist_fixture))
    r = client.get("/dist/maestrod-linux-amd64")
    assert r.status_code == 200
    assert r.content == b"FAKE_BINARY_AMD64"


def test_dist_serves_checksums(dist_fixture):
    client = TestClient(_app(dist_fixture))
    r = client.get("/dist/SHA256SUMS")
    assert r.status_code == 200
    assert b"maestrod-linux-amd64" in r.content


def test_dist_rejects_path_traversal(dist_fixture):
    client = TestClient(_app(dist_fixture))
    r = client.get("/dist/etc/passwd")
    assert r.status_code == 404


def test_install_script_substitutes_cp_url(dist_fixture):
    client = TestClient(_app(dist_fixture))
    r = client.get(
        "/install-daemon.sh",
        headers={"host": "playmaestro.cloud"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/x-shellscript")
    body = r.text
    assert 'DEFAULT_CP_URL=""' not in body
    assert "playmaestro.cloud" in body


def test_install_script_404_when_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("MAESTRO_DIST_DIR", str(tmp_path))
    monkeypatch.setenv("MAESTRO_INSTALL_SCRIPT", str(tmp_path / "nope.sh"))
    client = TestClient(create_app())
    r = client.get("/install-daemon.sh")
    assert r.status_code == 404
