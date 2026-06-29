"""Aggregate runtime + stored data into a single stats payload.

Everything here is read-only and defensive: a missing registry or an empty
store yields zeros rather than an error, so the dashboard always renders.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

from yumi.logging_config import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


def _safe(fn: Callable[[], T], default: T) -> T:
    try:
        return fn()
    except Exception:
        logger.debug("stats: source failed, using default", exc_info=True)
        return default


def _tool_stats() -> dict[str, Any]:
    import yumi.core.platform.runtime.accessors as acc
    from yumi.core.platform.tools.tool import TOOL_REGISTRY

    disabled = getattr(acc, "DISABLED_TOOLS", set()) or set()
    confirm = getattr(acc, "CONFIRMATION_TOOLS", set()) or set()
    edge_registry = getattr(acc, "EDGE_TOOLS_REGISTRY", {}) or {}
    active = getattr(acc, "ACTIVE_CONNECTIONS", {}) or {}

    server_total = len(TOOL_REGISTRY)
    server_disabled = sum(1 for n in TOOL_REGISTRY if n in disabled)
    edge_total = sum(len(m) for m in edge_registry.values())
    edge_online = sum(1 for k in edge_registry if k in active)

    return {
        "server_total": server_total,
        "server_enabled": server_total - server_disabled,
        "server_disabled": server_disabled,
        "require_confirmation": sum(1 for n in TOOL_REGISTRY if n in confirm),
        "edge_total": edge_total,
        "edge_devices": len(edge_registry),
        "edge_online": edge_online,
        "total": server_total + edge_total,
    }


def _session_stats(store: Any) -> dict[str, Any]:
    sessions = _safe(lambda: store.list_sessions(status="active"), [])
    total_messages = sum(int(s.get("message_count") or 0) for s in sessions)
    turn_counts = _safe(store.session_turn_counts, {})
    total_turns = sum(turn_counts.values())
    count = len(sessions)
    return {
        "active": count,
        "total_messages": total_messages,
        "total_turns": total_turns,
        "avg_messages": round(total_messages / count, 1) if count else 0.0,
    }


def _trace_stats() -> dict[str, Any]:
    from yumi.core.platform.tools.trace import snapshot_traces

    traces = _safe(lambda: snapshot_traces(), [])
    by_status: dict[str, int] = {}
    by_tool: dict[str, int] = {}
    total_duration = 0
    duration_n = 0
    edge_calls = 0
    for t in traces:
        status = str(t.get("status") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1
        name = str(t.get("display_name") or t.get("tool_name") or "unknown")
        by_tool[name] = by_tool.get(name, 0) + 1
        if t.get("edge_name"):
            edge_calls += 1
        dur = t.get("duration_ms")
        if isinstance(dur, (int, float)) and dur > 0:
            total_duration += dur
            duration_n += 1
    top_tools = sorted(by_tool.items(), key=lambda kv: kv[1], reverse=True)[:12]
    return {
        "total": len(traces),
        "edge_calls": edge_calls,
        "by_status": by_status,
        "top_tools": [{"name": n, "count": c} for n, c in top_tools],
        "avg_duration_ms": round(total_duration / duration_n) if duration_n else 0,
    }


def _token_stats(store: Any) -> dict[str, Any]:
    summary = _safe(
        store.token_usage_summary,
        {"turns": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "by_model": []},
    )
    daily = _safe(lambda: store.token_usage_timeseries(days=14), [])
    return {
        "total": summary.get("total_tokens", 0),
        "prompt": summary.get("prompt_tokens", 0),
        "completion": summary.get("completion_tokens", 0),
        "turns": summary.get("turns", 0),
        "by_model": summary.get("by_model", []),
        "daily": daily,
    }


def build_stats() -> dict[str, Any]:
    """Return the full analytics payload consumed by the Stats dashboard."""
    from yumi.core.features.memory.store import get_memory_store

    store = _safe(lambda: get_memory_store().sqlite, None)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tools": _safe(_tool_stats, {}),
        "sessions": _session_stats(store) if store is not None else {},
        "tool_calls": _safe(_trace_stats, {}),
        "tokens": _token_stats(store) if store is not None else {},
    }
