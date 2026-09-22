"""Application service: stream events for one Yumi chat turn.

This is the actual implementation, not a wrapper. The legacy
``_generate_chat_events_impl`` god function has been decomposed into the
``yumi.core.platform.dispatch`` collaborators; this orchestrator is now a small
state machine that wires them together.

Layering:

* ``yumi.core.features.chat.router`` — HTTP transport (quota, audit, NDJSON).
* ``yumi.core.features.chat.pipeline``        — public entry point; just calls this service.
* ``ChatTurnService``            — application orchestration (this module).
* ``yumi.core.platform.dispatch.*``      — domain (tool dispatch + observability).
* ``yumi.core.platform.runtime``         — infrastructure (mutable state registries).
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from copy import deepcopy

from yumi.core.features.chat.context import reset_chat_owner_user_id, set_chat_owner_user_id
from yumi.core.features.chat.language import build_turn_language_note
from yumi.core.features.chat.trace_sink import ChatTraceSink
from yumi.core.platform.dispatch import (
    LOCAL_TOOL_TIMEOUT_DEFAULT,
    MAX_TOOL_CALL_FORMAT_RETRIES,
    MAX_TOOL_LOOPS,
    TOOL_CALL_TIMEOUT_DEFAULT,
    TOOL_RESULT_MAX_CHARS,
    ConfirmationGate,
    EdgeToolExecutor,
    LocalToolExecutor,
    ToolCallNormalizer,
    ToolDispatcher,
    TurnContext,
    UsageRecorder,
)
from yumi.core.platform.dispatch.normalizer import summarize_tool_args
from yumi.core.platform.http.events import ErrorEvent, TextEvent, ThoughtEvent, ToolStatusEvent, TurnPhaseEvent
from yumi.core.platform.plugins import (
    SINGLE_USER_ID,
    get_bot_pool,
    get_current_identity,
    get_session_scope,
)
from yumi.core.platform.runtime import RuntimeState, get_default_runtime
from yumi.core.platform.runtime.assistant_context import PromptSnapshot
from yumi.core.platform.runtime.async_work import run_blocking
from yumi.core.platform.runtime.tool_catalog import model_visible_tool_schema
from yumi.core.platform.tools.context_prefetch import runtime_context_prompt_block
from yumi.core.platform.tools.replay import normalize_tool_history
from yumi.core.platform.tools.routing import ToolCatalog, select_tool_schemas
from yumi.logging_config import get_logger

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


def _assistant_tool_spans(messages: list[dict]) -> list[tuple[int, int]]:
    """Find ``assistant`` tool-call turns and their adjacent ``tool`` replies.

    Strict OpenAI/Gemini replay rules require us to remove this span from
    ``ephemeral_messages`` after persisting, so the next loop iteration does
    not duplicate it.
    """
    spans: list[tuple[int, int]] = []
    i = 0
    while i < len(messages):
        m = messages[i]
        if m.get("role") != "assistant" or not m.get("tool_calls"):
            i += 1
            continue
        j = i + 1
        while j < len(messages) and messages[j].get("role") == "tool":
            j += 1
        spans.append((i, j))
        i = j
    return spans


def _with_metrics(message: dict, tool_metrics: dict | None) -> dict:
    """Copy *message*, attaching its execution metrics when it is a tool result."""
    copy = dict(message)
    if tool_metrics and copy.get("role") == "tool":
        metrics = tool_metrics.get(str(copy.get("tool_call_id") or ""))
        if metrics:
            copy["yumi_tool_metrics"] = dict(metrics)
    return copy


def _persist_tool_ephemeral_spans(
    messages: list[dict],
    session_id: str,
    bot,
    tool_metrics: dict | None = None,
    *,
    turn_id: str = "",
    prompt_snapshot: PromptSnapshot | None = None,
) -> None:
    """Move completed assistant+tool spans out of the turn and into the transcript.

    ``tool_metrics`` (keyed by tool_call_id) is folded into the persisted copy
    only. The originals stay clean because they are still being sent to the
    provider, which forwards tool messages field-for-field.
    """
    spans = _assistant_tool_spans(messages)
    if not spans:
        return
    turns: list[list[dict]] = []
    for i, j in spans:
        turn: list[dict] = []
        for k in range(i, j):
            message = _with_metrics(messages[k], tool_metrics)
            message["turn_id"] = turn_id
            turn.append(message)
        turn = normalize_tool_history(turn, strict=True)
        turns.append(turn)
    memory = bot.session_memory(session_id)
    for turn in turns:
        memory.persist_openai_messages(turn)
    if prompt_snapshot is not None:
        for i, j in spans:
            prompt_snapshot.tool_messages.extend(normalize_tool_history(deepcopy(messages[i:j]), strict=True))
    for i, j in reversed(spans):
        del messages[i:j]


def _truncate_tool_result(result) -> str:
    """Bound tool-result text before it enters the context (and the transcript).

    Keeps head and tail with an explicit truncation marker so the model knows
    content was elided. Without a cap, one oversized edge/tool payload gets
    re-billed on every request that replays it from the recent-message window.
    """
    text = result if isinstance(result, str) else str(result)
    if len(text) <= TOOL_RESULT_MAX_CHARS:
        return text
    head = TOOL_RESULT_MAX_CHARS * 3 // 4
    tail = TOOL_RESULT_MAX_CHARS - head
    omitted = len(text) - head - tail
    return f"{text[:head]}\n...[tool result truncated: {omitted} of {len(text)} chars omitted]...\n{text[-tail:]}"


def _append_system_note(ctx: TurnContext, content: str | None) -> None:
    if not content:
        return
    note = {"role": "system", "content": content}
    if ctx.ephemeral_messages is None:
        ctx.ephemeral_messages = [note]
    else:
        ctx.ephemeral_messages.append(note)


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
        from yumi.core.platform.runtime.assistant_context import conversation_session

        session_token = conversation_session.set(session_id)
        ctx = TurnContext(
            prompt=prompt,
            session_id=session_id,
            think=think,
            timer_callback=timer_callback,
            owner_uid=owner_uid,
        )
        from yumi.core.platform.runtime.usage_context import usage_owner_id, usage_turn_id

        usage_owner_token = usage_owner_id.set(owner_uid or "")
        usage_turn_token = usage_turn_id.set(ctx.turn_id)
        from yumi.core.platform.runtime.embedding_cache import RequestEmbeddingCache, request_embedding_cache

        embedding_cache = RequestEmbeddingCache()
        embedding_cache_token = request_embedding_cache.set(embedding_cache)
        from yumi.core.features.memory.index_queue import defer_message_index

        index_token = defer_message_index.set(True)
        sink = ChatTraceSink(ctx)
        try:
            async for event in self._run_turn(ctx, sink):
                yield event
        finally:
            defer_message_index.reset(index_token)
            if sink.bot is not None:
                from yumi.core.features.memory.index_queue import start_worker

                try:
                    start_worker(sink.bot.session_memory(session_id))
                except Exception:
                    logger.warning("Deferred index scheduling failed; pending jobs retained", exc_info=True)
            embedding_cache.close()
            request_embedding_cache.reset(embedding_cache_token)
            usage_owner_id.reset(usage_owner_token)
            usage_turn_id.reset(usage_turn_token)
            conversation_session.reset(session_token)
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
            from yumi.core.platform.runtime.assistant_context import personal_store
            from yumi.core.platform.storage.assistant_store import is_personal_session

            if is_personal_session(ctx.session_id) and not ctx.timer_callback:
                current = personal_store(ctx.owner_uid).get("state", {})
                if current.get("session_id") != ctx.session_id:
                    yield {"type": "error", "code": "CONTEXT_CHANGED", "content": "Conversation restarted. Send again."}
                    return
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
            # After the turn (and after releasing the lock), check whether the
            # transcript outgrew its token budget and fold old turns into the
            # session summary in the background — see memory/compaction.py.
            # Lazy import: the architecture guard allows cross-feature use only
            # at call time (features must stay import-decoupled at load time).
            try:
                from yumi.core.features.memory.compaction import schedule_compaction

                schedule_compaction(ctx.session_id)
            except Exception:
                logger.debug("compaction scheduling skipped", exc_info=True)

        if sink.timing is not None:
            yield sink.timing

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
            yield sink.emit(TurnPhaseEvent(turn_id=ctx.turn_id, phase="preparing"))

            normalizer = ToolCallNormalizer(max_retries=MAX_TOOL_CALL_FORMAT_RETRIES)
            gate = ConfirmationGate(self.runtime)
            dispatcher = ToolDispatcher(
                self.runtime,
                local_executor=LocalToolExecutor(timeout=LOCAL_TOOL_TIMEOUT_DEFAULT),
                edge_executor=EdgeToolExecutor(self.runtime, default_timeout=TOOL_CALL_TIMEOUT_DEFAULT),
            )

            async for event in self._run_loops(ctx, sink, active_bot, usage, normalizer, gate, dispatcher):
                yield event
            await run_blocking(
                _persist_tool_ephemeral_spans,
                ctx.ephemeral_messages,
                ctx.session_id,
                active_bot,
                ctx.tool_metrics,
                turn_id=ctx.turn_id,
                prompt_snapshot=ctx.prompt_snapshot,
            )
        except Exception as exc:
            diag = sink.write_diagnostic("chat_pipeline_failed", error=exc, extra={"reason": "exception"})
            logger.exception("Chat pipeline failed session_id=%s diagnostic=%s", ctx.session_id, diag)
            content = f"Chat request failed: {exc}"
            if diag:
                content += f" Diagnostic saved to: {diag}"
            yield sink.emit(ErrorEvent(code="YUMI_CHAT_PIPELINE_FAILED", content=content))

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

        # Class-1 "context" tools: run them once before generating and inject the
        # results as an ephemeral note for THIS turn only. It is never persisted
        # (ephemeral_messages aren't saved), so an edge can expose e.g.
        # get_user_context() and the agent always sees fresh state (mood, plans,
        # ...) before replying. Per-tool errors are swallowed inside the helper;
        # this guard only covers a total failure.
        prefetch_started = time.perf_counter()
        try:
            from yumi.core.platform.storage.assistant_store import is_group_session

            runtime_context = None if is_group_session(ctx.session_id) else await runtime_context_prompt_block()
        except Exception as exc:
            logger.debug("Context prefetch failed: %s", exc)
            runtime_context = None
        from yumi.core.platform.observability.turn_inspector import record_stage

        record_stage(ctx.session_id, "context_prefetch_ms", (time.perf_counter() - prefetch_started) * 1000)
        _append_system_note(ctx, runtime_context)
        from yumi.core.features.assistant.personalization import preferences
        from yumi.core.platform.runtime.assistant_context import personal_store
        from yumi.core.platform.storage.assistant_store import is_personal_session

        language = (
            preferences(personal_store(ctx.owner_uid))["response_language"]
            if is_personal_session(ctx.session_id)
            else "auto"
        )
        _append_system_note(ctx, build_turn_language_note(ctx.prompt, language))

        # Tool routing runs ONCE per turn. Re-selecting inside the loop churned
        # the tool list between iterations (forced edge tools grow mid-turn),
        # and any change to the tools array invalidates the provider prompt
        # cache for the whole request. Newly activated edge tools are instead
        # appended to the frozen list below, preserving the existing prefix.
        turn_tools = await self._select_tools(ctx, routing_query)
        sink.record_routing()

        while True:
            ctx.loop_count += 1
            if ctx.loop_count > MAX_TOOL_LOOPS + 1:
                async for event in self._emit_loop_exhausted(ctx, sink):
                    yield event
                return

            turn_tools = self._with_forced_edge_tools(turn_tools, ctx)
            closing = ctx.loop_count > MAX_TOOL_LOOPS or ctx.tools_stopped_reason is not None
            if closing and not ctx.closing_requested:
                _append_system_note(
                    ctx,
                    "Tool execution has stopped for this request. "
                    + (ctx.tools_stopped_reason or "The tool-loop limit was reached.")
                    + " Do not call more tools. Give a concise final reply explaining completed work, "
                    "failed or unknown outcomes, and what remains. Never claim an unverified action succeeded.",
                )
                ctx.closing_requested = True
            tools = None if closing else turn_tools
            ctx.last_tools = tools

            yield sink.emit(TurnPhaseEvent(turn_id=ctx.turn_id, phase="model", round=ctx.loop_count))
            tool_calls_to_process, streamed_text, streamed_reasoning = None, "", ""
            finish_reason: str | None = None
            provider_finish_reason: str | None = None
            async for chunk in active_bot.chat_stream(
                prompt=current_prompt,
                session_id=ctx.session_id,
                tools=tools if tools else None,
                ephemeral_messages=ctx.ephemeral_messages,
                think=ctx.think,
                turn_id=ctx.turn_id,
                prompt_snapshot=ctx.prompt_snapshot,
                response_language=language,
            ):
                ctype = chunk.get("type")
                if ctype == "model_settings":
                    from yumi.core.platform.observability.turn_inspector import record_model_settings

                    record_model_settings(ctx.session_id, chunk)
                    continue
                if ctype == "usage":
                    usage.add(chunk)
                    sink.record_provider_usage(chunk)
                    continue
                if ctype == "finish":
                    finish_reason = str(chunk.get("reason") or "unknown")
                    raw_reason = chunk.get("provider_reason")
                    provider_finish_reason = str(raw_reason) if raw_reason is not None else None
                    sink.record_provider_finish(chunk)
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
                if finish_reason not in (None, "stop"):
                    diag = sink.write_diagnostic(
                        "chat_provider_finish",
                        extra={
                            "reason": finish_reason,
                            "provider_reason": provider_finish_reason,
                            "streamed_text_chars": len(streamed_text),
                            "streamed_reasoning_chars": len(streamed_reasoning),
                        },
                    )
                    if finish_reason == "length":
                        code = "YUMI_LLM_RESPONSE_TRUNCATED"
                        content = "The model reached its output limit, so the response may be incomplete."
                    elif finish_reason == "blocked":
                        code = "YUMI_LLM_RESPONSE_BLOCKED"
                        content = "The model provider blocked this response."
                    else:
                        code = "YUMI_LLM_FINISH_UNKNOWN"
                        detail = f" ({provider_finish_reason})" if provider_finish_reason else ""
                        content = f"The model stopped for an unrecognized reason{detail}."
                    if diag:
                        content += f" Diagnostic saved to: {diag}"
                    yield sink.emit(ErrorEvent(code=code, content=content))
                return

            # Keep malformed requests too: normalization may reject them and retry.
            sink.record_tool_calls(tool_calls_to_process)
            if closing:
                async for event in self._emit_loop_exhausted(ctx, sink):
                    yield event
                return

            outcome = normalizer.normalize(tool_calls_to_process, ctx)
            if outcome.kind == "exhausted":
                async for event in self._emit_normalize_exhausted(ctx, sink, tool_calls_to_process):
                    yield event
                return
            if outcome.kind == "retry":
                sink.record_provider_finish({"reason": "retry", "provider_reason": "invalid_tool_call"})
                yield sink.emit(
                    ToolStatusEvent(
                        status="error",
                        content=(
                            f"Tool call format invalid (attempt {outcome.retry_attempt}/"
                            f"{MAX_TOOL_CALL_FORMAT_RETRIES}); asking the model to regenerate."
                        ),
                    )
                )
                # Clear the prompt so the retry does not re-send and re-persist the
                # original user message (the normalizer already queued a regenerate note).
                current_prompt = None
                continue

            assert outcome.tcalls is not None
            sink.record_tool_calls(outcome.tcalls)
            asst_msg: dict = {"role": "assistant", "content": streamed_text, "tool_calls": outcome.tcalls}
            if streamed_reasoning:
                asst_msg["reasoning_content"] = streamed_reasoning
            ctx.ephemeral_messages.append(asst_msg)

            invocations, prep_events = dispatcher.prepare(outcome.tcalls, ctx)
            for ev in prep_events:
                yield sink.emit(ev)

            if not invocations:
                await run_blocking(
                    _persist_tool_ephemeral_spans,
                    ctx.ephemeral_messages,
                    ctx.session_id,
                    active_bot,
                    ctx.tool_metrics,
                    turn_id=ctx.turn_id,
                    prompt_snapshot=ctx.prompt_snapshot,
                )
                current_prompt = None
                continue

            approved: list = []
            async for event, inv in gate.filter(invocations, ctx):
                if event is not None:
                    yield sink.emit(event)
                if inv is not None:
                    approved.append(inv)

            if not approved:
                await run_blocking(
                    _persist_tool_ephemeral_spans,
                    ctx.ephemeral_messages,
                    ctx.session_id,
                    active_bot,
                    ctx.tool_metrics,
                    turn_id=ctx.turn_id,
                    prompt_snapshot=ctx.prompt_snapshot,
                )
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
                            content=inv.action_summary or f"Running local tool '{inv.func_name}'...",
                        )
                    )
                else:
                    yield sink.emit(
                        ToolStatusEvent(
                            status="running",
                            content=inv.action_summary
                            or f"Calling '{inv.original_tool_name}' on edge device '{inv.target_edge}'...",
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
                sink.record_tool_result(inv, result)
                if result.status == "unknown":
                    ctx.tools_stopped_reason = (
                        "A tool timed out and its outcome is unknown. Do not retry the action automatically."
                    )
                if result.status == "success":
                    yield sink.emit(
                        ToolStatusEvent(
                            status="success",
                            content=inv.action_summary or f"Tool {result.display_label} finished successfully.",
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
                    content = (
                        f"Tool {result.display_label} timed out; its outcome is unknown."
                        if result.status == "unknown"
                        else f"Tool {result.display_label} failed."
                    )
                    if diag:
                        content += f" Diagnostic saved to: {diag}"
                    yield sink.emit(ToolStatusEvent(status="error", content=content))

                ctx.ephemeral_messages.append(
                    {
                        "role": "tool",
                        "content": _truncate_tool_result(result.result),
                        "name": inv.tool_message_name,
                        "tool_call_id": inv.tool_call_id,
                    }
                )

                # discover_app_tools activated an edge for the session; expose
                # that edge's tools for the REST OF THIS TURN too, through the
                # append-only forced-tools path (keeps the sent prefix stable).
                if result.func_name == "discover_app_tools":
                    try:
                        payload = json.loads(str(result.result))
                        names = payload.get("activated_tool_names") or []
                        new_names = [n for n in names if isinstance(n, str)]
                        ctx.active_edge_tool_names.update(new_names)
                        ctx.recent_discovered_tools = new_names + [
                            n for n in ctx.recent_discovered_tools if n not in new_names
                        ]
                    except (json.JSONDecodeError, TypeError, AttributeError):
                        pass

            await run_blocking(
                _persist_tool_ephemeral_spans,
                ctx.ephemeral_messages,
                ctx.session_id,
                active_bot,
                ctx.tool_metrics,
                turn_id=ctx.turn_id,
                prompt_snapshot=ctx.prompt_snapshot,
            )
            current_prompt = None  # subsequent iterations use ephemeral_messages only

    # ---- helper paths -------------------------------------------------------

    async def _select_tools(self, ctx: TurnContext, routing_query: str) -> list | None:
        ident = get_current_identity()
        try:
            decision = await asyncio.to_thread(
                select_tool_schemas,
                identity=ident,
                query=routing_query,
                session_id=ctx.session_id,
                disabled_tools=self.runtime.tool_policy.disabled_tools,
                edge_registry=self.runtime.edge_registry.tools,
                force_edge_tool_names=ctx.active_edge_tool_names,
            )
            tools = decision.tools
            core_tools = list(getattr(decision, "core_tools", []) or [])
            selected_edge_tools = list(getattr(decision, "selected_edge_tools", []) or [])
            ctx.routing_summary = {
                "core_count": len(core_tools),
                "selected_edge_count": len(selected_edge_tools),
                "total_edge_count": int(getattr(decision, "total_edge_tools", 0) or 0),
                "dynamic_routing_enabled": bool(getattr(decision, "dynamic_routing_enabled", False)),
                "elapsed_ms": int(getattr(decision, "elapsed_ms", 0) or 0),
                "selected_edge_tools": [str(getattr(entry, "name", "")) for entry in selected_edge_tools],
                "pinned_edge_tools": [
                    str(getattr(entry, "name", "")) for entry in (getattr(decision, "pinned_edge_tools", []) or [])
                ],
                "forced_edge_tools": [
                    str(getattr(entry, "name", "")) for entry in (getattr(decision, "forced_edge_tools", []) or [])
                ],
                "mentioned_edge_tools": [
                    str(getattr(entry, "name", "")) for entry in (getattr(decision, "mentioned_edge_tools", []) or [])
                ],
                "retrieved_edge_tools": [
                    str(getattr(entry, "name", "")) for entry in (getattr(decision, "retrieved_edge_tools", []) or [])
                ],
            }
        except Exception as exc:
            logger.warning("Tool routing unavailable; continuing without tools: %s", exc)
            tools = []
            ctx.routing_summary = {
                "core_count": len(tools or []),
                "selected_edge_count": 0,
                "total_edge_count": 0,
                "dynamic_routing_enabled": False,
                "elapsed_ms": 0,
                "fallback": True,
            }
        from yumi.core.platform.runtime.assistant_context import personal_store
        from yumi.core.platform.storage.assistant_store import is_group_session, is_personal_session

        if is_group_session(ctx.session_id):
            return []
        if is_personal_session(ctx.session_id):
            saved = personal_store(ctx.owner_uid).get("tools", {})
            tools = [
                t
                for t in (tools or [])
                if not saved.get(t["function"]["name"], {}).get("disabled")
                and saved.get(t["function"]["name"], {}).get("ai_access") != "none"
            ]
        if ctx.timer_callback:
            tools = _exclude_delay_scheduling_tools(tools)
        return tools

    def _with_forced_edge_tools(self, tools: list | None, ctx: TurnContext) -> list | None:
        """Append schemas for edge tools activated mid-turn without re-ranking.

        Appending (in sorted order) keeps the already-sent tool prefix stable;
        a full re-selection would reorder the list and invalidate the provider
        prompt cache from position zero.
        """
        from yumi.core.platform.storage.assistant_store import is_group_session

        if is_group_session(ctx.session_id):
            return None
        catalog = ToolCatalog(
            identity=get_current_identity(),
            disabled_tools=self.runtime.tool_policy.disabled_tools,
            edge_registry=self.runtime.edge_registry.tools,
        )
        visible = {entry.name: entry for entry in catalog.core_tools() + catalog.edge_tools()}
        # Recheck existing schemas too: access can change during confirmation.
        out = [t for t in (tools or []) if t.get("function", {}).get("name") in visible]
        present = {t["function"]["name"] for t in out}
        for name in sorted(ctx.active_edge_tool_names - present):
            if name in visible:
                out.append(model_visible_tool_schema(visible[name].schema))
        from yumi.core.features.config import load_model_config
        from yumi.core.platform.providers.budget import fit_tool_schemas

        if ctx.timer_callback:
            out = _exclude_delay_scheduling_tools(out) or []
        return (
            fit_tool_schemas(
                out, budget=load_model_config().tool_schema_token_budget, priority_names=ctx.recent_discovered_tools
            )
            or None
        )

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
