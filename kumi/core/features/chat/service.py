"""Application service: stream events for one Kumi chat turn.

This is the actual implementation, not a wrapper. The legacy
``_generate_chat_events_impl`` god function has been decomposed into the
``kumi.core.platform.dispatch`` collaborators; this orchestrator is now a small
state machine that wires them together.

Layering:

* ``kumi.core.features.chat.router`` — HTTP transport (quota, audit, NDJSON).
* ``kumi.core.features.chat.pipeline``        — public entry point; just calls this service.
* ``ChatTurnService``            — application orchestration (this module).
* ``kumi.core.platform.dispatch.*``      — domain (tool dispatch + observability).
* ``kumi.core.platform.runtime``         — infrastructure (mutable state registries).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from kumi.core.features.chat.context import reset_chat_owner_user_id, set_chat_owner_user_id
from kumi.core.features.chat.trace_sink import ChatTraceSink
from kumi.core.platform.dispatch import (
    LOCAL_TOOL_TIMEOUT_DEFAULT,
    MAX_TOOL_CALL_FORMAT_RETRIES,
    MAX_TOOL_LOOPS,
    TOOL_CALL_TIMEOUT_DEFAULT,
    ConfirmationGate,
    EdgeToolExecutor,
    LocalToolExecutor,
    ToolCallNormalizer,
    ToolDispatcher,
    TurnContext,
    UsageRecorder,
)
from kumi.core.platform.dispatch.normalizer import summarize_tool_args
from kumi.core.platform.http.events import ErrorEvent, TextEvent, ThoughtEvent, ToolStatusEvent
from kumi.core.platform.plugins import (
    SINGLE_USER_ID,
    get_bot_pool,
    get_current_identity,
    get_session_scope,
)
from kumi.core.platform.runtime import RuntimeState, get_default_runtime
from kumi.core.platform.tools.routing import select_tool_schemas
from kumi.logging_config import get_logger

logger = get_logger(__name__)

# When a *timer fires*, the planned action should run now — not schedule another delay.
_DELAY_SCHEDULING_TOOL_NAMES = frozenset({"set_timer", "schedule_task"})


def _exclude_delay_scheduling_tools(tools: list | None) -> list | None:
    if not tools:
        return tools
    out: list = [
        t
        for t in tools
        if not (
            isinstance(t, dict)
            and isinstance(t.get("function"), dict)
            and t["function"].get("name") in _DELAY_SCHEDULING_TOOL_NAMES
        )
    ]
    return out or None


def _tail_assistant_tool_span(messages: list[dict]) -> tuple[int, int] | None:
    """Find the last ``assistant`` tool-call turn and its ``tool`` replies.

    Strict OpenAI/Gemini replay rules require us to remove this span from
    ``ephemeral_messages`` after persisting, so the next loop iteration does
    not duplicate it.
    """
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i]
        if m.get("role") != "assistant" or not m.get("tool_calls"):
            continue
        j = i + 1
        while j < len(messages) and messages[j].get("role") == "tool":
            j += 1
        return (i, j)
    return None


def _persist_tool_ephemeral_tail(messages: list[dict], session_id: str, bot) -> None:
    span = _tail_assistant_tool_span(messages)
    if not span:
        return
    i, j = span
    turn = [dict(messages[k]) for k in range(i, j)]
    bot.session_memory(session_id).persist_openai_messages(turn)
    del messages[i:j]


class ChatTurnService:
    """Orchestrates one ``/chat`` turn end-to-end."""

    def __init__(self, runtime: RuntimeState | None = None) -> None:
        self.runtime = runtime or get_default_runtime()

    async def stream_chat_turn(
        self,
        prompt: str,
        session_id: str,
        *,
        think: bool = False,
        timer_callback: bool = False,
    ) -> AsyncIterator[dict]:
        owner_uid = get_session_scope().owner_user_from_session_id(session_id)
        owner_token = set_chat_owner_user_id(owner_uid)
        ctx = TurnContext(
            prompt=prompt,
            session_id=session_id,
            think=think,
            timer_callback=timer_callback,
            owner_uid=owner_uid,
        )
        sink = ChatTraceSink(ctx)
        try:
            async for event in self._run_turn(ctx, sink):
                yield event
        finally:
            reset_chat_owner_user_id(owner_token)

    # ------------------------------------------------------------------------

    async def _run_turn(self, ctx: TurnContext, sink: ChatTraceSink) -> AsyncIterator[dict]:
        lock = self.runtime.session_locks.get(ctx.session_id)
        await lock.acquire()
        # ``UsageRecorder`` is constructed up-front (outside the try/except) so the
        # finally block can always persist whatever totals were collected, even if
        # the pipeline never reached the bot lookup. ``__exit__`` records the
        # totals through the quota plugin port; the context manager protocol just
        # gives us a deterministic "always run on cleanup" hook.
        usage = UsageRecorder(ctx, bot=None, owner_uid=ctx.owner_uid)
        try:
            async for event in self._dispatch(ctx, sink, usage):
                yield event
        finally:
            try:
                sink.record_turn_end(
                    total_prompt_tokens=usage.total_prompt_tokens,
                    total_completion_tokens=usage.total_completion_tokens,
                    usage_model=usage.usage_model,
                )
            except Exception:
                logger.debug("chat trace turn_end skipped", exc_info=True)
            usage.__exit__(None, None, None)
            self.runtime.session_locks.prune_if_needed()
            lock.release()

    async def _dispatch(
        self,
        ctx: TurnContext,
        sink: ChatTraceSink,
        usage: UsageRecorder,
    ) -> AsyncIterator[dict]:
        """Run the pipeline; surface any exception as a streamed error event.

        The orchestrator wraps every potential failure point — identity check,
        bot pool lookup, provider stream, tool dispatch — in one try/except
        so callers always see a streamed ``{"type": "error", ...}`` instead of
        an HTTP-level traceback. This mirrors the legacy contract that the
        ``test_oss_app_boot`` suite enforces.
        """
        try:
            ident = get_current_identity()
            if ident.user_id not in (SINGLE_USER_ID, ctx.owner_uid):
                yield sink.emit(
                    ErrorEvent(
                        code="FORBIDDEN",
                        content="Session does not belong to the current user",
                    )
                )
                return

            active_bot = await get_bot_pool().get_bot_for_session_owner(ctx.owner_uid)
            sink.bot = active_bot
            usage.bot = active_bot
            sink.record_turn_begin()

            normalizer = ToolCallNormalizer(max_retries=MAX_TOOL_CALL_FORMAT_RETRIES)
            gate = ConfirmationGate(self.runtime)
            dispatcher = ToolDispatcher(
                self.runtime,
                local_executor=LocalToolExecutor(timeout=LOCAL_TOOL_TIMEOUT_DEFAULT),
                edge_executor=EdgeToolExecutor(self.runtime, default_timeout=TOOL_CALL_TIMEOUT_DEFAULT),
            )

            async for event in self._run_loops(ctx, sink, active_bot, usage, normalizer, gate, dispatcher):
                yield event
            _persist_tool_ephemeral_tail(ctx.ephemeral_messages, ctx.session_id, active_bot)
        except Exception as exc:
            diag = sink.write_diagnostic("chat_pipeline_failed", error=exc, extra={"reason": "exception"})
            logger.exception("Chat pipeline failed session_id=%s diagnostic=%s", ctx.session_id, diag)
            content = f"Chat request failed: {exc}"
            if diag:
                content += f" Diagnostic saved to: {diag}"
            yield sink.emit(ErrorEvent(code="KUMI_CHAT_PIPELINE_FAILED", content=content))

    async def _run_loops(
        self,
        ctx: TurnContext,
        sink: ChatTraceSink,
        active_bot,
        usage: UsageRecorder,
        normalizer: ToolCallNormalizer,
        gate: ConfirmationGate,
        dispatcher: ToolDispatcher,
    ) -> AsyncIterator[dict]:
        current_prompt = ctx.prompt
        routing_query = ctx.prompt
        while True:
            ctx.loop_count += 1
            if ctx.loop_count > MAX_TOOL_LOOPS:
                async for event in self._emit_loop_exhausted(ctx, sink):
                    yield event
                return

            tools = self._select_tools(ctx, routing_query)
            ctx.last_tools = tools

            tool_calls_to_process, streamed_text, streamed_reasoning = None, "", ""
            async for chunk in active_bot.chat_stream(
                prompt=current_prompt,
                session_id=ctx.session_id,
                tools=tools if tools else None,
                ephemeral_messages=ctx.ephemeral_messages,
                think=ctx.think,
            ):
                ctype = chunk.get("type")
                if ctype == "usage":
                    usage.add(chunk)
                    sink.record_provider_usage(chunk)
                    continue
                if ctype == "text":
                    streamed_text += chunk["content"]
                    yield sink.emit(TextEvent(content=chunk["content"]))
                elif ctype == "thought":
                    # Stash the reasoning so it can be replayed back to the
                    # provider on the next turn — DeepSeek's thinking models
                    # reject otherwise once tool_calls are involved.
                    streamed_reasoning += chunk.get("content", "")
                    yield sink.emit(ThoughtEvent(content=chunk["content"]))
                elif ctype == "tool_call":
                    tool_calls_to_process = chunk["tool_calls"]
                    break

            if not tool_calls_to_process:
                ctx.tool_format_retries = 0
                return

            outcome = normalizer.normalize(tool_calls_to_process, ctx)
            if outcome.kind == "exhausted":
                async for event in self._emit_normalize_exhausted(ctx, sink, tool_calls_to_process):
                    yield event
                return
            if outcome.kind == "retry":
                yield sink.emit(
                    ToolStatusEvent(
                        status="error",
                        content=(
                            f"Tool call format invalid (attempt {outcome.retry_attempt}/"
                            f"{MAX_TOOL_CALL_FORMAT_RETRIES}); asking the model to regenerate."
                        ),
                    )
                )
                continue

            assert outcome.tcalls is not None
            asst_msg: dict = {"role": "assistant", "content": streamed_text, "tool_calls": outcome.tcalls}
            if streamed_reasoning:
                asst_msg["reasoning_content"] = streamed_reasoning
            ctx.ephemeral_messages.append(asst_msg)

            invocations, prep_events = dispatcher.prepare(outcome.tcalls, ctx)
            for ev in prep_events:
                yield sink.emit(ev)

            if not invocations:
                _persist_tool_ephemeral_tail(ctx.ephemeral_messages, ctx.session_id, active_bot)
                current_prompt = None
                continue

            approved: list = []
            async for event, inv in gate.filter(invocations, ctx):
                if event is not None:
                    yield sink.emit(event)
                if inv is not None:
                    approved.append(inv)

            if not approved:
                _persist_tool_ephemeral_tail(ctx.ephemeral_messages, ctx.session_id, active_bot)
                current_prompt = None
                continue

            for inv in approved:
                if inv.kind == "local":
                    logger.info(
                        "Tool call: %s session_id=%s args=%s",
                        inv.func_name,
                        ctx.session_id,
                        dispatcher.summarize_args(inv.args),
                    )
                    yield sink.emit(
                        ToolStatusEvent(
                            status="running",
                            content=f"Running local tool '{inv.func_name}'...",
                        )
                    )
                else:
                    yield sink.emit(
                        ToolStatusEvent(
                            status="running",
                            content=f"Calling '{inv.original_tool_name}' on edge device '{inv.target_edge}'...",
                        )
                    )

            results = await dispatcher.run_all(approved, ctx)
            for inv, result in zip(approved, results):
                ctx.tool_loop_events.append(
                    {
                        "loop": ctx.loop_count,
                        "tool": inv.tool_message_name,
                        "resolved_tool": result.func_name,
                        "kind": inv.kind,
                        "edge": inv.target_edge,
                        "status": result.status,
                        "result_preview": str(result.result)[:1000],
                    }
                )
                if result.status == "success":
                    yield sink.emit(
                        ToolStatusEvent(
                            status="success",
                            content=f"Tool {result.display_label} finished successfully.",
                        )
                    )
                else:
                    diag = sink.write_diagnostic(
                        "chat_tool_execution",
                        extra={
                            "reason": "tool_execution_failed",
                            "failed_tool": inv.tool_message_name,
                            "resolved_tool": result.func_name,
                            "tool_kind": inv.kind,
                            "edge": inv.target_edge,
                            "arguments_preview": dispatcher.summarize_args(inv.args, max_len=2000),
                            "result_preview": str(result.result)[:2000],
                        },
                    )
                    content = f"Tool {result.display_label} failed."
                    if diag:
                        content += f" Diagnostic saved to: {diag}"
                    yield sink.emit(ToolStatusEvent(status="error", content=content))

                ctx.ephemeral_messages.append({"role": "tool", "content": result.result, "name": inv.tool_message_name})

            current_prompt = None  # subsequent iterations use ephemeral_messages only

    # ---- helper paths -------------------------------------------------------

    def _select_tools(self, ctx: TurnContext, routing_query: str) -> list | None:
        ident = get_current_identity()
        try:
            decision = select_tool_schemas(
                identity=ident,
                query=routing_query,
                session_id=ctx.session_id,
                disabled_tools=self.runtime.tool_policy.disabled_tools,
                edge_registry=self.runtime.edge_registry.tools,
                force_edge_tool_names=ctx.active_edge_tool_names,
            )
            tools = decision.tools
        except Exception as exc:
            logger.warning("Dynamic tool routing failed; falling back to all tool schemas: %s", exc)
            tools = self.runtime.tool_catalog.all_tool_schemas(ident)
        if ctx.timer_callback:
            tools = _exclude_delay_scheduling_tools(tools)
        return tools

    async def _emit_loop_exhausted(self, ctx: TurnContext, sink: ChatTraceSink) -> AsyncIterator[dict]:
        diag = sink.write_loop_diagnostic(max_tool_loops=MAX_TOOL_LOOPS)
        if diag:
            logger.error(
                "Maximum tool execution iterations reached session_id=%s diagnostic=%s",
                ctx.session_id,
                diag,
            )
        else:
            logger.error("Maximum tool execution iterations reached session_id=%s", ctx.session_id)
        content = "System: Maximum tool execution iterations reached. Stopping to prevent infinite loops."
        if diag:
            content += f" Diagnostic saved to: {diag}"
        yield sink.emit(ErrorEvent(content=content))

    async def _emit_normalize_exhausted(
        self,
        ctx: TurnContext,
        sink: ChatTraceSink,
        raw_tool_calls,
    ) -> AsyncIterator[dict]:
        diag = sink.write_diagnostic(
            "chat_tool_call_format",
            extra={
                "reason": "max_tool_call_format_retries",
                "max_tool_call_format_retries": MAX_TOOL_CALL_FORMAT_RETRIES,
                "raw_tool_calls_preview": summarize_tool_args({"tool_calls": raw_tool_calls}, max_len=2000),
            },
        )
        content = (
            "Model returned tool_calls that could not be parsed into a usable format "
            f"after {MAX_TOOL_CALL_FORMAT_RETRIES} automatic re-tries."
        )
        if diag:
            logger.error(
                "Tool call format retries exhausted session_id=%s diagnostic=%s",
                ctx.session_id,
                diag,
            )
            content += f" Diagnostic saved to: {diag}"
        yield sink.emit(ErrorEvent(content=content))
