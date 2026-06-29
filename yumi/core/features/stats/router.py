"""Analytics dashboard route."""

from __future__ import annotations

from fastapi import APIRouter
from yumi.core.features.stats.service import build_stats
from yumi.core.platform.http.dependencies import CurrentIdentity

router = APIRouter()


# Sync handler on purpose: FastAPI runs plain `def` routes in a worker thread, so
# the blocking SQLite/registry aggregation in build_stats() never stalls the event
# loop (and the chat SSE / edge websocket traffic sharing it).
@router.get("/stats")
def stats_endpoint(identity: CurrentIdentity):  # noqa: ARG001 — auth/scoping dependency
    """Aggregate tool, token, session, and tool-call metrics for the dashboard."""
    return build_stats()
