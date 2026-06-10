"""Restrict OpenAPI/Swagger to admin-scoped principals (no-op in OSS single-user)."""

from __future__ import annotations

import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from yumi.core.platform.plugins import get_current_identity, has_admin_scope


class DocsAccessMiddleware(BaseHTTPMiddleware):
    """Allow ``/docs`` and ``/openapi.json`` for admin-scoped identities.

    Set ``YUMI_EXPOSE_DOCS=1`` to disable this gate entirely.

    Single-user mode always returns an admin-scoped identity, so this is
    transparently a pass-through unless a plugin supplies stricter identity.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        if (
            path not in ("/docs", "/openapi.json", "/redoc")
            and not path.startswith("/docs/")
            and not path.startswith("/redoc")
        ):
            return await call_next(request)
        expose = os.getenv("YUMI_EXPOSE_DOCS", "").strip().lower() in ("1", "true", "yes")
        if expose:
            return await call_next(request)
        ident = get_current_identity()
        if not has_admin_scope(ident):
            return JSONResponse(
                status_code=403,
                content={"detail": "OpenAPI/docs require admin scope or set YUMI_EXPOSE_DOCS=1."},
            )
        return await call_next(request)
