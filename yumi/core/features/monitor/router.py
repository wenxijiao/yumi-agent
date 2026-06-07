"""Monitoring routes."""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from yumi.core.platform.http.dependencies import CurrentIdentity
from yumi.core.platform.plugins import get_session_scope
from yumi.core.platform.runtime.accessors import ACTIVE_CONNECTIONS, DISABLED_TOOLS, EDGE_TOOLS_REGISTRY
from yumi.core.platform.tools.tool import TOOL_REGISTRY
from yumi.core.platform.tools.trace import export_traces_json_lines, list_traces

router = APIRouter()


@router.get("/monitor/topology")
async def monitor_topology_endpoint(identity: CurrentIdentity):  # noqa: ARG001
    edges: list[dict] = []
    for edge_key, tools_map in EDGE_TOOLS_REGISTRY.items():
        edges.append(
            {
                "edge_name": edge_key,
                "online": edge_key in ACTIVE_CONNECTIONS,
                "tool_count": len(tools_map),
                "shared": False,
            }
        )
    local_enabled = sum(1 for n in TOOL_REGISTRY if n not in DISABLED_TOOLS)
    return {
        "server": {"id": "yumi-core", "label": "Yumi Core", "role": "chat_server"},
        "local_tool_count": local_enabled,
        "edges": edges,
    }


@router.get("/monitor/traces")
async def monitor_traces_endpoint(
    identity: CurrentIdentity,
    session_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    scope = get_session_scope()
    sid = scope.qualify_session_http(identity, session_id) if session_id else None
    return {"traces": list_traces(session_id=sid, limit=limit)}


@router.get("/monitor/traces/export")
async def monitor_traces_export_endpoint(identity: CurrentIdentity, session_id: str | None = None):
    scope = get_session_scope()
    sid = scope.qualify_session_http(identity, session_id) if session_id else None
    body = export_traces_json_lines(session_id=sid)
    return StreamingResponse(
        iter([body]),
        media_type="application/x-ndjson; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="yumi_tool_traces.ndjson"'},
    )
