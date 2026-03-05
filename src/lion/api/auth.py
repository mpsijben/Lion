"""Optional API key authentication middleware."""

from __future__ import annotations

from typing import Iterable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


class ApiKeyAuthMiddleware(BaseHTTPMiddleware):
    """Bearer token middleware, disabled when no keys are configured."""

    def __init__(
        self,
        app,
        api_keys: Iterable[str],
        public_paths: Iterable[str] | None = None,
    ):
        super().__init__(app)
        self._keys = {k for k in api_keys if k}
        self._public_paths = set(public_paths or [])

    async def dispatch(self, request: Request, call_next):
        if not self._keys:
            return await call_next(request)

        path = request.url.path
        if request.method == "OPTIONS" or any(path.startswith(p) for p in self._public_paths):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={
                    "error_code": "unauthorized",
                    "message": "Missing bearer token",
                    "detail": "Set Authorization: Bearer <api-key>",
                },
            )

        token = auth_header[len("Bearer ") :].strip()
        if token not in self._keys:
            return JSONResponse(
                status_code=401,
                content={
                    "error_code": "unauthorized",
                    "message": "Invalid API key",
                    "detail": "The provided bearer token is not recognized",
                },
            )

        return await call_next(request)
