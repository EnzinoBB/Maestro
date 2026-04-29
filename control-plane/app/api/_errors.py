"""Custom error response shape for HTTPException raised inside /api/*."""
from __future__ import annotations

from typing import Any

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
        body: dict[str, Any] = {"code": code}
        if isinstance(exc.detail, str):
            body["message"] = exc.detail
        elif isinstance(exc.detail, dict):
            # Endpoint-supplied dict wins; handler defaults fill in only the keys
            # the endpoint did not provide. Lets endpoints emit a custom 'code'
            # (e.g. for sub-cases that share a status) without it being silently
            # dropped.
            body = {"code": code, "message": "request failed", **exc.detail}
        else:
            body["message"] = "request failed"
        return JSONResponse(
            status_code=exc.status_code,
            content={"ok": False, "error": body},
        )
