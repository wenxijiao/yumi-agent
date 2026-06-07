"""Tool dispatcher: prepare invocations, then run local + edge in parallel.

Two responsibilities, deliberately co-located so the orchestrator can ask:

    invocations, errors = dispatcher.prepare(tcalls, ctx)
    results = await dispatcher.run_all(invocations)

The classification logic (local vs edge, edge offline check, JSON repair on
arguments, ``set_timer/schedule_task`` session-id stamping) lives in
``prepare``. Concrete execution lives in ``LocalToolExecutor`` and
``EdgeToolExecutor``; this class just routes by ``invocation.kind``.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from json_repair import repair_json
from kumi.core.api.events import ChatEvent, ToolStatusEvent
from kumi.core.dispatch.context import ToolInvocation, ToolResult, TurnContext
from kumi.core.dispatch.edge import EdgeToolExecutor
from kumi.core.dispatch.local import LocalToolExecutor
from kumi.core.dispatch.normalizer import summarize_tool_args
from kumi.core.runtime import RuntimeState
from kumi.core.runtime.edge_naming import (
    edge_tool_key_prefix,
    edge_tool_register_prefix,
    parse_edge_connection_key,
    resolve_edge_for_prefixed_tool_name,
)
from kumi.core.tool import TOOL_REGISTRY
from kumi.core.tool_trace import record_tool_trace


def canonical_local_tool_name(raw: str) -> str:
    """Map model-emitted names to ``TOOL_REGISTRY`` keys (case, ``functions.`` prefix)."""
    fn = (raw or "").strip()
    if not fn:
        return fn
    if fn.startswith("functions."):
        fn = fn[len("functions.") :]
    if fn.startswith("edge_"):
        return fn
    if fn in TOOL_REGISTRY:
        return fn
    lower = fn.lower()
    if lower in TOOL_REGISTRY:
        return lower
    return fn


class ToolDispatcher:
    """Prepares and executes a batch of tool calls coming from one model turn."""

    def __init__(
        self,
        runtime: RuntimeState,
        *,
        local_executor: LocalToolExecutor,
        edge_executor: EdgeToolExecutor,
    ) -> None:
        self.runtime = runtime
        self.local_executor = local_executor
        self.edge_executor = edge_executor

    # ---- preparation --------------------------------------------------------

    def prepare(
        self,
        tcalls: list[dict],
        ctx: TurnContext,
    ) -> tuple[list[ToolInvocation], list[ChatEvent]]:
        """Classify and validate ``tcalls``.

        Returns ``(invocations, error_events)`` — the orchestrator should
        emit each ``error_events`` entry as a ``tool_status`` and append a
        matching ``tool`` message into ``ctx.ephemeral_messages`` (already
        done here, the events are for the live stream only).
        """
        invocations: list[ToolInvocation] = []
        events: list[ChatEvent] = []

        for tc in tcalls:
            raw_call_name = str(tc["function"]["name"]).strip()
            args, parse_err = self._parse_arguments(tc["function"]["arguments"], raw_call_name)
            if parse_err is not None:
                ctx.ephemeral_messages.append({"role": "tool", "content": parse_err, "name": raw_call_name})
                ctx.tool_loop_events.append(
                    {
                        "loop": ctx.loop_count,
                        "tool": raw_call_name,
                        "status": "error",
                        "reason": "invalid_json_arguments",
                        "detail": parse_err[:1000],
                    }
                )
                events.append(
                    ToolStatusEvent(
                        status="error",
                        content=f"Tool '{raw_call_name}': invalid JSON arguments",
                    )
                )
                continue

            func_name = canonical_local_tool_name(raw_call_name)
            if func_name in TOOL_REGISTRY:
                # Timer callbacks default-stamp the active session so follow-up
                # turns land in the originating session, not "default".
                if func_name in ("set_timer", "schedule_task") and args.get("session_id", "default") == "default":
                    args["session_id"] = ctx.session_id
                invocations.append(
                    ToolInvocation(
                        kind="local",
                        func_name=func_name,
                        tool_message_name=raw_call_name,
                        args=args,
                    )
                )
                continue

            edge_inv, edge_event = self._resolve_edge_invocation(raw_call_name, func_name, args, ctx)
            if edge_event is not None:
                events.append(edge_event)
            if edge_inv is not None:
                # active_edge_tool_names becomes "force include in tool schema for the
                # rest of this turn" (chat_turn.py:367). We add only when the
                # invocation actually runs — not at prepare-time — so a denied
                # confirmation does not keep the tool sticky in subsequent loops.
                invocations.append(edge_inv)

        return invocations, events

    @staticmethod
    def _parse_arguments(args: Any, tool_name: str) -> tuple[dict, str | None]:
        """Coerce ``args`` into a dict; on failure return an error message."""
        if isinstance(args, dict):
            return args, None
        if not isinstance(args, str):
            return {}, None
        try:
            parsed = json.loads(args)
            if isinstance(parsed, dict):
                return parsed, None
        except json.JSONDecodeError:
            pass
        try:
            repaired = repair_json(args, return_objects=True)
            if isinstance(repaired, dict):
                return repaired, None
        except Exception:
            pass
        msg = (
            f"Error: Invalid JSON in arguments for tool '{tool_name}'. "
            f"Raw input: {args!r}. Please retry with valid JSON."
        )
        return {}, msg

    def _resolve_edge_invocation(
        self,
        raw_call_name: str,
        func_name: str,
        args: dict,
        ctx: TurnContext,
    ) -> tuple[ToolInvocation | None, ChatEvent | None]:
        target_edge = resolve_edge_for_prefixed_tool_name(func_name, self.runtime.edge_registry)
        original_tool_name = func_name
        if target_edge is not None:
            owner_id, edge_simple = parse_edge_connection_key(target_edge)
            prefix = edge_tool_register_prefix(owner_id, edge_simple) if owner_id else edge_tool_key_prefix(edge_simple)
            if func_name.startswith(prefix):
                original_tool_name = func_name[len(prefix) :]

        if not target_edge:
            if func_name.startswith("edge_"):
                err = f"Tool '{func_name}' targets an edge device that is offline or not connected."
            else:
                err = (
                    f"Tool '{raw_call_name}' is not registered on this Kumi server "
                    f"(resolved as '{func_name}'). Restart the server after upgrading, "
                    "and check the Tools page that it is not disabled."
                )
            ctx.ephemeral_messages.append({"role": "tool", "content": f"Error: {err}", "name": raw_call_name})
            ctx.tool_loop_events.append(
                {
                    "loop": ctx.loop_count,
                    "tool": raw_call_name,
                    "resolved_tool": func_name,
                    "status": "error",
                    "reason": "tool_not_registered_or_edge_offline",
                    "detail": err,
                }
            )
            return None, ToolStatusEvent(status="error", content=err)

        peer = self.runtime.edge_registry.active_connections.get(target_edge)
        if peer is None:
            ctx.ephemeral_messages.append(
                {"role": "tool", "content": "Error: Device offline or tool not found.", "name": raw_call_name}
            )
            ctx.tool_loop_events.append(
                {
                    "loop": ctx.loop_count,
                    "tool": raw_call_name,
                    "resolved_tool": func_name,
                    "status": "error",
                    "reason": "edge_device_went_offline",
                    "edge": target_edge,
                }
            )
            return None, ToolStatusEvent(
                status="error",
                content=f"Edge device '{target_edge}' went offline before tool execution started.",
            )

        return (
            ToolInvocation(
                kind="edge",
                func_name=func_name,
                tool_message_name=raw_call_name,
                args=args,
                target_edge=target_edge,
                original_tool_name=original_tool_name,
                peer=peer,
            ),
            None,
        )

    # ---- execution ----------------------------------------------------------

    async def run_all(self, invocations: list[ToolInvocation], ctx: TurnContext) -> list[ToolResult]:
        """Run all invocations in parallel, emit tool traces, return results in order."""
        return await asyncio.gather(*[self._timed_run_one(inv, ctx) for inv in invocations])

    async def _timed_run_one(self, inv: ToolInvocation, ctx: TurnContext) -> ToolResult:
        t0 = time.perf_counter()
        result = await self._run_one(inv)
        dt_ms = int((time.perf_counter() - t0) * 1000)
        display = inv.original_tool_name if inv.kind == "edge" and inv.original_tool_name else inv.func_name
        record_tool_trace(
            session_id=ctx.session_id,
            tool_name=inv.func_name,
            kind=inv.kind,
            edge_name=inv.target_edge,
            display_name=display,
            arguments=inv.args,
            status=result.status,
            duration_ms=dt_ms,
            result_preview=str(result.result)[:500],
        )
        return result

    async def _run_one(self, inv: ToolInvocation) -> ToolResult:
        if inv.kind == "local":
            return await self.local_executor.run(inv)
        return await self.edge_executor.run(inv)

    # ---- helpers reused by orchestrator -------------------------------------

    @staticmethod
    def summarize_args(args: dict | None, max_len: int = 500) -> str:
        return summarize_tool_args(args, max_len)
