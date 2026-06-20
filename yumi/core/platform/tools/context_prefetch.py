"""Class-1 "context" tools — prefetch + inject.

A tool flagged ``proactive_context`` is a *context provider*: instead of being
offered to the model to call, it is run automatically before a generation and
its result is injected as context for that one turn (never persisted to
history). This drives such tools for BOTH the proactive-message service and the
normal chat pipeline, so it lives in platform — features depend on platform,
not on each other.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

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


async def _call_edge_context(full_name: str, entry: dict[str, Any], args: dict[str, Any]) -> str:
    target_edge = None
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


async def context_prefetch_lines() -> list[str]:
    """Run every tool flagged ``proactive_context`` and return formatted context
    lines to inject into one generation (a proactive message OR a chat turn).

    Local and edge tools are both supported. A tool whose required params aren't
    covered by its fixed ``proactive_context_args`` is skipped. Failures are
    swallowed — context is best-effort and must never break a turn.
    """
    lines: list[str] = []
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
            lines.append(f"{_context_label(name, schema, tool_data)}: {str(result)[:1000]}")
        except Exception as exc:
            logger.debug("Context tool %s failed: %s", name, exc)

    for edge_tools in EDGE_TOOLS_REGISTRY.values():
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
                result = await _call_edge_context(full_name, entry, args)
                lines.append(f"{_context_label(full_name, schema, entry)}: {result[:1000]}")
            except Exception as exc:
                logger.debug("Edge context tool %s failed: %s", full_name, exc)
    return lines
