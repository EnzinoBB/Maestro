"""Endpoints that serve the daemon binary bundle and a templated installer.

These are part of Layer 1 of the installer design (2026-04-22). They let a
running control plane act as a self-serve install source for new daemons.
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse


router = APIRouter()


def _dist_dir() -> Path:
    return Path(os.environ.get("MAESTRO_DIST_DIR", "/opt/maestro-cp/dist"))


def _install_script() -> Path:
    return Path(
        os.environ.get(
            "MAESTRO_INSTALL_SCRIPT",
            "/opt/maestro-cp/scripts/install-daemon.sh",
        )
    )


# Files we are willing to serve from the dist dir. Keep this whitelist
# restrictive to avoid path-traversal surprises.
_DIST_ALLOWED = {
    "maestrod-linux-amd64",
    "maestrod-linux-arm64",
    "maestrod-darwin-amd64",
    "maestrod-darwin-arm64",
    "SHA256SUMS",
}


@router.get("/dist/{name}")
def serve_dist(name: str):
    if name not in _DIST_ALLOWED:
        raise HTTPException(status_code=404)
    path = _dist_dir() / name
    if not path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(
        path=str(path),
        media_type="application/octet-stream",
        filename=name,
    )


@router.get("/install-daemon.sh")
def serve_install_script(request: Request) -> Response:
    path = _install_script()
    if not path.is_file():
        raise HTTPException(status_code=404)
    body = path.read_text(encoding="utf-8")
    # Substitute the placeholder DEFAULT_CP_URL="" with the URL of this CP.
    # Prefer MAESTRO_PUBLIC_URL when set (defends against Host-header
    # poisoning and fixes scheme when behind a TLS-terminating proxy);
    # fall back to the request's scheme + Host header otherwise.
    public = os.environ.get("MAESTRO_PUBLIC_URL")
    if public:
        cp_url = public.rstrip("/")
    else:
        cp_url = f"{request.url.scheme}://{request.headers.get('host', request.url.netloc)}"
    body = body.replace('DEFAULT_CP_URL=""', f'DEFAULT_CP_URL="{cp_url}"')
    return Response(
        content=body,
        media_type="text/x-shellscript; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )
