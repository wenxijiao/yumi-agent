"""User-confirmation gate for tool invocations.

Yields a ``tool_confirmation`` event for any invocation that requires
approval, awaits the user's decision via the runtime's pending-confirmation
future map, and persists the policy when the user picks ``always_allow``.

The gate yields ``(event_to_emit | None, accepted_invocation | None)``
tuples so the orchestrator can stream events while keeping confirmation
serial — exactly what the legacy code did, but separated from the rest of
the loop.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

from kumi.core.platform.dispatch.context import ToolInvocation, TurnContext
from kumi.core.platform.http.events import ChatEvent, ToolConfirmationEvent, ToolStatusEvent
from kumi.core.platform.runtime import RuntimeState
from kumi.core.platform.runtime.edge_naming import (
    edge_tool_key_prefix,
    edge_tool_register_prefix,
    parse_edge_connection_key,
)
from kumi.core.platform.tools.tool_trace import record_tool_trace


class ConfirmationGate:
    """Sequential approval check for a batch of prepared tool invocations."""

    CONFIRMATION_TIMEOUT_SECONDS = 120

    def __init__(self, runtime: RuntimeState) -> None:
        self.runtime = runtime

    async def filter(
        self,
        invocations: list[ToolInvocation],
        ctx: TurnContext,
    ) -> AsyncIterator[tuple[ChatEvent | None, ToolInvocation | None]]:
        """Stream events; yield each *approved* invocation alongside any UI events.

        Caller iterates and:
          * forwards every emitted ``event`` to the HTTP layer,
          * collects each ``invocation`` into the run-list.
        """
        policy = self.runtime.tool_policy
        registry = self.runtime.edge_registry.tools

        def _approved(inv: ToolInvocation) -> ToolInvocation:
            # Mark the edge tool as "force-include in subsequent loops" only when
            # confirmation actually granted it — not at prepare-time, otherwise a
            # denied tool would stay sticky in the schema for the rest of the turn.
            if inv.kind == "edge":
                ctx.active_edge_tool_names.add(inv.func_name)
            return inv

        for inv in invocations:
            fn = inv.func_name
            if fn in policy.always_allowed_tools:
                yield None, _approved(inv)
                continue

            edge_requires = False
            if inv.kind == "edge" and inv.target_edge:
                edge_meta = registry.get(inv.target_edge, {}).get(fn)
                if edge_meta:
                    edge_requires = bool(edge_meta.get("require_confirmation"))
            needs_confirm = fn in policy.confirmation_tools or edge_requires
            if not needs_confirm:
                yield None, _approved(inv)
                continue

            confirm_id = str(uuid.uuid4())
            confirm_future: asyncio.Future = asyncio.get_running_loop().create_future()
            policy.pending_confirmations[confirm_id] = confirm_future

            display_name = inv.original_tool_name if inv.kind == "edge" and inv.original_tool_name else fn
            yield (
                ToolConfirmationEvent(
                    call_id=confirm_id,
                    tool_name=display_name,
                    full_tool_name=fn,
                    arguments=inv.args,
                ),
                None,
            )

            try:
                decision = await asyncio.wait_for(confirm_future, timeout=self.CONFIRMATION_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                decision = "deny"
            finally:
                policy.pending_confirmations.pop(confirm_id, None)

            if decision == "deny":
                ctx.ephemeral_messages.append(
                    {"role": "tool", "content": "Tool execution was denied by the user.", "name": fn}
                )
                ctx.tool_loop_events.append(
                    {
                        "loop": ctx.loop_count,
                        "tool": fn,
                        "status": "denied",
                        "reason": "user_denied_confirmation",
                    }
                )
                yield (
                    ToolStatusEvent(
                        status="error",
                        content=f"Tool '{display_name}' denied by user.",
                    ),
                    None,
                )
                record_tool_trace(
                    session_id=ctx.session_id,
                    tool_name=fn,
                    kind=inv.kind,
                    edge_name=inv.target_edge,
                    display_name=display_name,
                    arguments=inv.args,
                    status="denied",
                    duration_ms=0,
                    result_preview="User denied confirmation",
                )
                continue

            if decision == "always_allow":
                await self._mark_always_allowed(inv)

            yield None, _approved(inv)

    async def _mark_always_allowed(self, inv: ToolInvocation) -> None:
        """Persist an ``always_allow`` decision so the user isn't asked again."""
        policy = self.runtime.tool_policy
        policy.confirmation_tools.discard(inv.func_name)
        policy.always_allowed_tools.add(inv.func_name)

        if inv.kind == "edge":
            from kumi.core.api.edge import _push_confirmation_policy_to_edge_peer

            peer = inv.peer
            en = inv.target_edge
            if peer is None or en is None:
                return
            oid, es = parse_edge_connection_key(en)
            tp = edge_tool_register_prefix(oid, es) if oid else edge_tool_key_prefix(es)
            try:
                await _push_confirmation_policy_to_edge_peer(peer, en, tp)
            except Exception:
                pass
        else:
            from kumi.core.api.edge import persist_local_tool_confirmation_to_config

            persist_local_tool_confirmation_to_config()
