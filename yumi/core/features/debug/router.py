"""Debug / observability aggregation for the admin web UI.

One endpoint that answers "why can't Yumi see my edge tool?" at a glance:
the connected edges (+ resolved owner), recent tool-routing decisions (how
many edge tools were VISIBLE vs SELECTED each turn), recent tool calls, and
an auto-diagnosis that turns those raw signals into a plain-language verdict.

All data here is process-global and unauthenticated, matching the rest of the
single-user admin surface; identity plugins can scope it per user.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from yumi.core.platform.http.dependencies import CurrentIdentity
from yumi.core.platform.plugins import has_admin_scope
from yumi.core.platform.runtime.accessors import ACTIVE_CONNECTIONS, EDGE_TOOLS_REGISTRY
from yumi.core.platform.runtime.edge_naming import parse_edge_connection_key, split_edge_prefixed_tool
from yumi.core.platform.tools.routing import list_tool_routing_traces
from yumi.core.platform.tools.trace import list_traces

router = APIRouter()


def _config_snapshot() -> dict:
    """The routing knobs that decide edge-tool visibility, for the page to show."""
    from yumi.core.features.config import load_model_config

    try:
        cfg = load_model_config()
    except Exception:
        return {}
    return {
        "dynamic_routing_enabled": bool(getattr(cfg, "edge_tools_enable_dynamic_routing", True)),
        "edge_tools_retrieval_limit": int(getattr(cfg, "edge_tools_retrieval_limit", 20)),
        "edge_tools_always_expose_below": int(getattr(cfg, "edge_tools_always_expose_below", 0)),
        "embedding_model_set": bool(getattr(cfg, "embedding_model", None)),
    }


def _edges_snapshot() -> list[dict]:
    """Every edge currently in the registry, with its resolved owner + tools."""
    edges: list[dict] = []
    for connection_key, tools_map in EDGE_TOOLS_REGISTRY.items():
        owner, edge_name = parse_edge_connection_key(connection_key)
        tools = []
        for prefixed_name, entry in tools_map.items():
            _, original = split_edge_prefixed_tool(prefixed_name)
            tools.append(
                {
                    "name": original or prefixed_name,
                    "full_name": prefixed_name,
                    "always_include": bool(entry.get("always_include")),
                    "require_confirmation": bool(entry.get("require_confirmation")),
                }
            )
        tools.sort(key=lambda t: t["name"])
        edges.append(
            {
                "connection_key": connection_key,
                "edge_name": edge_name,
                "owner_user_id": owner,
                "online": connection_key in ACTIVE_CONNECTIONS,
                "tool_count": len(tools_map),
                "tools": tools,
            }
        )
    edges.sort(key=lambda e: e["edge_name"])
    return edges


def _routing_traces(limit: int) -> list[dict]:
    """Recent routing DECISIONS (drop the interleaved token-usage rows)."""
    out: list[dict] = []
    for rec in list_tool_routing_traces(limit=limit * 2):
        if rec.get("type") == "usage":
            continue
        out.append(rec)
        if len(out) >= limit:
            break
    return out


def _diagnose(edges: list[dict], routing_traces: list[dict], identity) -> list[dict]:
    """Translate the raw signals into a plain-language verdict."""
    diags: list[dict] = []
    total_edge_tools = sum(e["tool_count"] for e in edges)
    num_online = sum(1 for e in edges if e["online"])
    ident_uid = getattr(identity, "user_id", None)

    if not edges:
        diags.append({"level": "info", "message": "No edge devices are connected to this server."})
        return diags

    recent = routing_traces[:10]
    if not recent:
        diags.append(
            {
                "level": "info",
                "message": (
                    f"{num_online} edge device(s) connected with {total_edge_tools} tool(s), but no "
                    "chat turns are recorded yet — send a message in chat, then refresh this page."
                ),
            }
        )
        return diags

    max_visible = max((int(r.get("total_edge_count") or 0) for r in recent), default=0)
    max_selected = max((int(r.get("selected_edge_count") or 0) for r in recent), default=0)

    if total_edge_tools > 0 and max_visible == 0:
        diags.append(
            {
                "level": "warning",
                "message": (
                    f"{total_edge_tools} edge tool(s) are connected, but recent chat turns saw 0 "
                    f"VISIBLE edge tools for the chatting identity ({ident_uid!r}). This is almost "
                    "always an account/owner mismatch: the edge registered under a different account "
                    "than the chat, or the channel (Telegram/etc.) is not linked to the edge's account."
                ),
            }
        )
    elif max_visible > 0 and max_selected == 0:
        diags.append(
            {
                "level": "warning",
                "message": (
                    f"Edge tools are visible ({max_visible}) but 0 were selected in recent turns — "
                    "check edge_tools_retrieval_limit (0 hides all un-pinned tools) and dynamic routing."
                ),
            }
        )
    else:
        diags.append(
            {
                "level": "ok",
                "message": (
                    f"Edge tools are connected and reaching the model ({max_selected} selected in a "
                    "recent turn)."
                ),
            }
        )
    return diags


@router.get("/debug/observability")
async def debug_observability_endpoint(
    identity: CurrentIdentity,
    limit: int = Query(default=50, ge=1, le=500),
):
    # Global view (all edges/traces across users) — admin only. In OSS single-user
    # the local identity always has admin scope, so this is a no-op there.
    if not has_admin_scope(identity):
        raise HTTPException(status_code=403, detail="Admin scope required for debug observability.")
    edges = _edges_snapshot()
    routing_traces = _routing_traces(limit)
    tool_calls = list_traces(limit=limit)
    return {
        "identity": {"user_id": getattr(identity, "user_id", None)},
        "config": _config_snapshot(),
        "edges": edges,
        "routing_traces": routing_traces,
        "tool_calls": tool_calls,
        "diagnosis": _diagnose(edges, routing_traces, identity),
    }
