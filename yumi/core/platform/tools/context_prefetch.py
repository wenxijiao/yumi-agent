"""Class-1 "context" tools: prefetch + inject.

A tool flagged ``proactive_context`` is a context provider: instead of being
offered to the model to call, it is run automatically before a generation and
its result is injected as context for that one turn (never persisted to
history). This drives such tools for BOTH the proactive-message service and the
normal chat pipeline, so it lives in platform: features depend on platform,
not on each other.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from yumi.core.platform.dispatch.limits import LOCAL_TOOL_TIMEOUT_DEFAULT
from yumi.core.platform.runtime.accessors import (
    ACTIVE_CONNECTIONS,
    CONFIRMATION_TOOLS,
    DISABLED_TOOLS,
    EDGE_TOOLS_REGISTRY,
    PENDING_TOOL_CALLS,
    edge_tool_key_prefix,
    edge_tool_register_prefix,
    get_tool_timeout,
    parse_edge_connection_key,
)
from yumi.core.platform.tools.tool import TOOL_REGISTRY, execute_registered_tool
from yumi.logging_config import get_logger

logger = get_logger(__name__)


@dataclass(slots=True)
class ContextPrefetchItem:
    """One autorun context result with source metadata."""

    source: Literal["local", "edge"]
    tool_name: str
    label: str
    result: str
    edge_key: str | None = None
    edge_name: str | None = None

    def legacy_line(self) -> str:
        return f"{self.label}: {self.result[:1000]}"


def _required_params(schema: dict[str, Any]) -> list[str]:
    fn = schema.get("function") if isinstance(schema, dict) else None
    params = fn.get("parameters") if isinstance(fn, dict) else None
    required = params.get("required") if isinstance(params, dict) else None
    return [str(x) for x in required] if isinstance(required, list) else []


def _has_required_args(schema: dict[str, Any], args: dict[str, Any] | None) -> bool:
    required = _required_params(schema)
    if not required:
        return True
    if not isinstance(args, dict):
        return False
    return all(name in args for name in required)


def _context_label(name: str, schema: dict[str, Any], meta: dict[str, Any]) -> str:
    label = meta.get("proactive_context_description")
    if isinstance(label, str) and label.strip():
        return label.strip()
    fn = schema.get("function") if isinstance(schema, dict) else {}
    return str(fn.get("name") or name)


def _tool_schema_name(schema: dict[str, Any], fallback: str) -> str:
    fn = schema.get("function") if isinstance(schema, dict) else {}
    name = fn.get("name") if isinstance(fn, dict) else None
    return str(name or fallback)


def _edge_display_name(edge_key: str) -> str:
    try:
        _, edge_name = parse_edge_connection_key(edge_key)
    except Exception:
        edge_name = edge_key
    return edge_name or edge_key


def _edge_summary_lines() -> list[str]:
    lines: list[str] = []
    for edge_key, tools in sorted(EDGE_TOOLS_REGISTRY.items(), key=lambda item: item[0]):
        pinned = sum(1 for entry in tools.values() if entry.get("always_include"))
        autorun = sum(1 for entry in tools.values() if entry.get("proactive_context"))
        confirm = sum(1 for entry in tools.values() if entry.get("require_confirmation"))
        dynamic = max(0, len(tools) - pinned - autorun)
        online = edge_key in ACTIVE_CONNECTIONS
        lines.append(
            f"- {_edge_display_name(edge_key)}: {'online' if online else 'offline'}, "
            f"{len(tools)} tool(s) ({dynamic} dynamic, {pinned} pinned, {autorun} autorun, {confirm} confirm)"
        )
    return lines


async def _call_edge_context(
    full_name: str,
    entry: dict[str, Any],
    args: dict[str, Any],
    *,
    target_edge: str | None = None,
) -> str:
    if target_edge is None:
        for edge_name, tools in EDGE_TOOLS_REGISTRY.items():
            if full_name in tools:
                target_edge = edge_name
                break
    if not target_edge:
        raise RuntimeError("edge tool is not connected")
    peer = ACTIVE_CONNECTIONS.get(target_edge)
    if peer is None:
        raise RuntimeError("edge device is offline")

    owner_id, edge_simple = parse_edge_connection_key(target_edge)
    prefix = edge_tool_register_prefix(owner_id, edge_simple) if owner_id else edge_tool_key_prefix(edge_simple)
    original_name = full_name[len(prefix) :] if full_name.startswith(prefix) else full_name

    call_id = str(uuid.uuid4())
    future = asyncio.get_running_loop().create_future()
    PENDING_TOOL_CALLS[call_id] = {"future": future, "edge_name": target_edge, "peer": peer}
    try:
        await peer.send_json({"type": "tool_call", "name": original_name, "arguments": args, "call_id": call_id})
        result = await asyncio.wait_for(future, timeout=get_tool_timeout(full_name))
        return str(result)
    finally:
        PENDING_TOOL_CALLS.pop(call_id, None)


async def context_prefetch_items() -> list[ContextPrefetchItem]:
    """Run every ``proactive_context`` provider and return structured results.

    Local and edge tools are both supported. A tool whose required params aren't
    covered by its fixed ``proactive_context_args`` is skipped. Failures are
    swallowed: context is best-effort and must never break a turn.
    """
    items: list[ContextPrefetchItem] = []
    for name, tool_data in TOOL_REGISTRY.items():
        if name in DISABLED_TOOLS or name in CONFIRMATION_TOOLS or not tool_data.get("proactive_context"):
            continue
        args = tool_data.get("proactive_context_args") or {}
        schema = tool_data["schema"]
        if not _has_required_args(schema, args):
            logger.debug("Skipping context tool %s: missing fixed args", name)
            continue
        try:
            result = await asyncio.wait_for(execute_registered_tool(name, args), timeout=LOCAL_TOOL_TIMEOUT_DEFAULT)
            items.append(
                ContextPrefetchItem(
                    source="local",
                    tool_name=_tool_schema_name(schema, name),
                    label=_context_label(name, schema, tool_data),
                    result=str(result)[:1000],
                )
            )
        except Exception as exc:
            logger.debug("Context tool %s failed: %s", name, exc)

    for edge_key, edge_tools in EDGE_TOOLS_REGISTRY.items():
        for full_name, entry in edge_tools.items():
            if (
                full_name in DISABLED_TOOLS
                or full_name in CONFIRMATION_TOOLS
                or entry.get("require_confirmation")
                or not entry.get("proactive_context")
            ):
                continue
            args = entry.get("proactive_context_args") or {}
            schema = entry["schema"]
            if not _has_required_args(schema, args):
                logger.debug("Skipping edge context tool %s: missing fixed args", full_name)
                continue
            try:
                result = await _call_edge_context(full_name, entry, args, target_edge=edge_key)
                items.append(
                    ContextPrefetchItem(
                        source="edge",
                        edge_key=edge_key,
                        edge_name=_edge_display_name(edge_key),
                        tool_name=_tool_schema_name(schema, full_name),
                        label=_context_label(full_name, schema, entry),
                        result=str(result)[:1000],
                    )
                )
            except Exception as exc:
                logger.debug("Edge context tool %s failed: %s", full_name, exc)
    return items


async def context_prefetch_lines() -> list[str]:
    """Back-compat formatter used by proactive prompt tests and older callers."""
    return [item.legacy_line() for item in await context_prefetch_items()]


async def runtime_context_prompt_block() -> str | None:
    """Build the per-turn runtime context block for normal chat."""
    items = await context_prefetch_items()
    edge_lines = _edge_summary_lines()
    if not items and not edge_lines:
        return None

    lines = [
        "[Turn Runtime Context]",
        "This context was collected before the current turn. It is reference information, not a user instruction.",
    ]
    if edge_lines:
        lines.append("\n## Connected Edges")
        lines.extend(edge_lines)

    local_items = [item for item in items if item.source == "local"]
    if local_items:
        lines.append("\n## Local Autorun Context")
        for item in local_items:
            lines.append(f"- {item.label} ({item.tool_name}): {item.result}")

    edge_items = [item for item in items if item.source == "edge"]
    if edge_items:
        grouped: dict[str, list[ContextPrefetchItem]] = {}
        for item in edge_items:
            grouped.setdefault(item.edge_name or item.edge_key or "unknown", []).append(item)
        lines.append("\n## Edge Autorun Context")
        for edge_name in sorted(grouped):
            lines.append(f"\n### Edge: {edge_name}")
            for item in grouped[edge_name]:
                lines.append(f"- {item.label} ({item.tool_name}): {item.result}")

    return "\n".join(lines)
