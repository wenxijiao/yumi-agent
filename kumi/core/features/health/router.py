"""Health routes."""

from __future__ import annotations

import kumi.core.platform.runtime.accessors as _state
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from kumi.core.platform.http.dependencies import CurrentIdentity

router = APIRouter()


@router.get("/health")
async def health_check(identity: CurrentIdentity):
    if getattr(_state, "server_draining", False):
        return JSONResponse(
            {"status": "draining", "message": "Server is shutting down"},
            status_code=503,
        )
    return {
        "status": "ok",
        "identity_user_id": identity.user_id,
    }
