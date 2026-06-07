"""Single sink for chat-turn observability.

Centralises three sources of side-effect that used to be scattered across
``_generate_chat_events_impl``:

* per-event NDJSON tracing (``chat_debug_trace.append_*``),
* turn-level diagnostics on failure (``write_chat_diagnostic`` /
  ``write_chat_loop_diagnostic``),
* fan-out of provider usage records.

Callers ``sink.emit(event)`` with a typed :class:`~kumi.core.api.events.ChatEvent`;
the sink records the event then returns it so the orchestrator can ``yield``
it directly. The HTTP boundary (``kumi.core.api.chat.generate_chat_events``)
serialises models to dicts only at the public edge.
"""

from __future__ import annotations

from typing import Any

from kumi.core.api import chat_debug_trace
from kumi.core.api.events import ChatEvent
from kumi.core.platform.dispatch.context import TurnContext
from kumi.core.platform.providers.diagnostics import write_chat_diagnostic, write_chat_loop_diagnostic


class ChatTraceSink:
    """Wraps the trace recorder so collaborators don't need to know it exists."""

    def __init__(self, ctx: TurnContext, *, bot: Any | None = None) -> None:
        self.ctx = ctx
        self.bot = bot

    # ---- live event tracing -------------------------------------------------

    def emit(self, event: ChatEvent) -> ChatEvent:
        """Record *event* in the per-session debug trace if active and return it.

        Returns the event unchanged so the orchestrator can ``yield sink.emit(...)``
        in one expression and downstream code keeps the typed model.
        """
        if chat_debug_trace.is_tracing(self.ctx.session_id):
            chat_debug_trace.append_stream_event(self.ctx.session_id, event.model_dump())
        return event

    def record_provider_usage(self, chunk: dict) -> None:
        if chat_debug_trace.is_tracing(self.ctx.session_id):
            chat_debug_trace.append_record(self.ctx.session_id, {"kind": "provider_usage", "usage": dict(chunk)})

    def record_turn_begin(self) -> None:
        if chat_debug_trace.is_tracing(self.ctx.session_id):
            chat_debug_trace.append_turn_begin(
                self.ctx.session_id,
                prompt=self.ctx.prompt,
                think=self.ctx.think,
                timer_callback=self.ctx.timer_callback,
            )

    def record_turn_end(
        self,
        *,
        total_prompt_tokens: int,
        total_completion_tokens: int,
        usage_model: str,
    ) -> None:
        if not chat_debug_trace.is_tracing(self.ctx.session_id):
            return
        try:
            chat_debug_trace.append_turn_end(
                self.ctx.session_id,
                model=self.bot.model_name if self.bot is not None else None,
                total_prompt_tokens=total_prompt_tokens,
                total_completion_tokens=total_completion_tokens,
                usage_model=usage_model,
            )
        except Exception:
            from kumi.logging_config import get_logger

            get_logger(__name__).debug("chat trace turn_end skipped", exc_info=True)

    # ---- diagnostics on failure ---------------------------------------------

    def write_diagnostic(
        self,
        phase: str,
        *,
        error: BaseException | None = None,
        extra: dict | None = None,
    ) -> str | None:
        return write_chat_diagnostic(
            phase=phase,
            session_id=self.ctx.session_id,
            prompt=self.ctx.prompt,
            model=self.bot.model_name if self.bot is not None else None,
            messages=self.ctx.ephemeral_messages,
            tools=self.ctx.last_tools,
            error=error,
            extra={
                "loop_count": self.ctx.loop_count,
                "active_edge_tool_names": sorted(self.ctx.active_edge_tool_names),
                "tool_loop_events": self.ctx.tool_loop_events[-80:],
                **(extra or {}),
            },
        )

    def write_loop_diagnostic(self, *, max_tool_loops: int) -> str | None:
        return write_chat_loop_diagnostic(
            session_id=self.ctx.session_id,
            prompt=self.ctx.prompt,
            model=self.bot.model_name if self.bot is not None else None,
            loop_count=self.ctx.loop_count - 1,
            messages=self.ctx.ephemeral_messages,
            tools=self.ctx.last_tools,
            extra={
                "reason": "maximum_tool_execution_iterations",
                "max_tool_loops": max_tool_loops,
                "active_edge_tool_names": sorted(self.ctx.active_edge_tool_names),
                "tool_loop_events": self.ctx.tool_loop_events[-80:],
            },
        )
