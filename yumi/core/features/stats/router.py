"""Analytics dashboard route."""

from __future__ import annotations

from fastapi import APIRouter
from yumi.core.features.stats.service import build_stats
from yumi.core.platform.http.dependencies import CurrentIdentity

router = APIRouter()


@router.get("/stats")
async def stats_endpoint(identity: CurrentIdentity):  # noqa: ARG001 — auth/scoping dependency
    """Aggregate tool, token, session, and tool-call metrics for the dashboard."""
    return build_stats()
