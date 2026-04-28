"""Custom error response shape for HTTPException raised inside /api/*."""
from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse


_CODE_BY_STATUS = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_exc_handler(request: Request, exc: HTTPException):
        # Only reshape /api/* responses; leave the rest (static, healthz) alone.
        if not request.url.path.startswith("/api/"):
            return JSONResponse(
                status_code=exc.status_code, content={"detail": exc.detail},
            )
        code = _CODE_BY_STATUS.get(exc.status_code, "error")
        # If detail is a dict (e.g., for 409 conflicts), preserve it as-is
        if isinstance(exc.detail, dict):
            return JSONResponse(
                status_code=exc.status_code,
                content={"ok": False, "error": exc.detail},
            )
        message = (
            exc.detail if isinstance(exc.detail, str)
            else "request failed"
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"ok": False, "error": {"code": code, "message": message}},
        )
