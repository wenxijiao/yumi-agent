"""ChatTurnService state-machine branches.

Covers loops in ``_run_loops`` that previously had no direct unit tests:
* happy path — text-only stream returns cleanly
* MAX_TOOL_LOOPS exhaustion produces an error event
* normalize-exhausted produces an error event
* owner-mismatch yields FORBIDDEN

The service yields :class:`yumi.core.platform.http.events.ChatEvent` Pydantic models;
serialisation to dicts happens at the HTTP boundary in ``core.api.chat``.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from yumi.core.features.chat.service import ChatTurnService, _persist_tool_ephemeral_spans
from yumi.core.platform.dispatch import MAX_TOOL_LOOPS
from yumi.core.platform.plugins.identity import Identity, set_current_identity
from yumi.core.platform.runtime import RuntimeState


class _FakeBot:
    model_name = "fake-model"

    def __init__(self, scripted_chunks: list[list[dict]]) -> None:
        self._calls = list(scripted_chunks)
        self.call_count = 0

    async def chat_stream(self, **kwargs) -> AsyncIterator[dict]:  # noqa: ARG002
        self.call_count += 1
        chunks = self._calls.pop(0) if self._calls else []
        for c in chunks:
            yield c

    def session_memory(self, _session_id: str):
        class _M:
            def persist_openai_messages(self, _messages):
                pass

        return _M()


class _FakeBotPool:
    def __init__(self, bot: _FakeBot) -> None:
        self._bot = bot

    async def get_bot_for_session_owner(self, owner_user_id: str) -> _FakeBot:  # noqa: ARG002
        return self._bot


@pytest.fixture
def runtime():
    return RuntimeState()


@pytest.fixture
def install_fakes(monkeypatch):
    """Wire a fake bot pool, scope, and tool routing into chat_turn."""
    from yumi.core.platform.plugins.identity import LOCAL_IDENTITY, reset_current_identity

    token = set_current_identity(LOCAL_IDENTITY)

    def install(bot: _FakeBot):
        import yumi.core.features.chat.service as svc

        monkeypatch.setattr(svc, "get_bot_pool", lambda: _FakeBotPool(bot))

        class _Scope:
            def owner_user_from_session_id(self, _sid: str) -> str:
                return LOCAL_IDENTITY.user_id

        monkeypatch.setattr(svc, "get_session_scope", lambda: _Scope())
        monkeypatch.setattr(
            svc,
            "select_tool_schemas",
            lambda **_kwargs: type("D", (), {"tools": None})(),
        )

    yield install
    reset_current_identity(token)


async def _drain(stream):
    return [ev async for ev in stream]


def test_happy_path_text_only_stream(runtime, install_fakes):
    bot = _FakeBot(scripted_chunks=[[{"type": "text", "content": "hello"}]])
    install_fakes(bot)

    svc = ChatTurnService(runtime)
    events = asyncio.run(_drain(svc.stream_chat_turn("hi", "s1")))
    text_events = [e for e in events if getattr(e, "type", None) == "text"]
    assert any(e.content == "hello" for e in text_events)
    assert bot.call_count == 1


def test_normal_provider_finish_is_internal(runtime, install_fakes):
    bot = _FakeBot(
        scripted_chunks=[
            [
                {"type": "text", "content": "hello"},
                {"type": "finish", "reason": "stop", "provider_reason": "end_turn"},
            ]
        ]
    )
    install_fakes(bot)

    events = asyncio.run(_drain(ChatTurnService(runtime).stream_chat_turn("hi", "s_finish_stop")))

    assert [event.type for event in events] == ["turn_phase", "turn_phase", "text", "turn_timing"]
    assert events[-1].duration_ms >= 0
    assert events[-1].confirmation_wait_ms == 0


@pytest.mark.parametrize(
    ("reason", "code"),
    [
        ("length", "YUMI_LLM_RESPONSE_TRUNCATED"),
        ("blocked", "YUMI_LLM_RESPONSE_BLOCKED"),
        ("unknown", "YUMI_LLM_FINISH_UNKNOWN"),
    ],
)
def test_abnormal_provider_finish_emits_error(runtime, install_fakes, monkeypatch, reason, code):
    bot = _FakeBot(
        scripted_chunks=[
            [
                {"type": "text", "content": "partial"},
                {"type": "finish", "reason": reason, "provider_reason": "raw_reason"},
            ]
        ]
    )
    install_fakes(bot)
    monkeypatch.setattr("yumi.core.features.chat.trace_sink.write_chat_diagnostic", lambda **_kwargs: None)

    events = asyncio.run(_drain(ChatTurnService(runtime).stream_chat_turn("hi", f"s_finish_{reason}")))

    assert any(event.type == "text" and event.content == "partial" for event in events)
    errors = [event for event in events if event.type == "error"]
    assert len(errors) == 1
    assert errors[0].code == code


def test_max_tool_loops_emits_error(runtime, install_fakes):
    """Looping ``unknown tool`` calls drives loop_count past MAX_TOOL_LOOPS."""
    chunks_per_iter = [
        {
            "type": "tool_call",
            "tool_calls": [{"id": "c0", "function": {"name": "nope_tool", "arguments": "{}"}}],
        }
    ]
    scripts = [
        [{**chunks_per_iter[0], "tool_calls": [{"id": f"c{i}", "function": {"name": "nope_tool", "arguments": {}}}]}]
        for i in range(MAX_TOOL_LOOPS + 2)
    ]
    bot = _FakeBot(scripted_chunks=scripts)
    install_fakes(bot)

    svc = ChatTurnService(runtime)
    events = asyncio.run(_drain(svc.stream_chat_turn("hi", "s2")))
    errs = [e for e in events if getattr(e, "type", None) == "error"]
    assert errs, "expected an error event after exhausting tool loops"
    assert any("Maximum tool execution iterations" in e.content for e in errs)
    assert bot.call_count == MAX_TOOL_LOOPS + 1


def test_loop_limit_gets_one_final_no_tools_summary(runtime, install_fakes):
    requests = []

    class Bot(_FakeBot):
        async def chat_stream(self, **kwargs):
            requests.append(kwargs)
            async for chunk in super().chat_stream(**kwargs):
                yield chunk

    scripts = [
        [{"type": "tool_call", "tool_calls": [{"id": f"c{i}", "function": {"name": "missing_tool", "arguments": {}}}]}]
        for i in range(MAX_TOOL_LOOPS)
    ]
    scripts.append(
        [
            {"type": "text", "content": "The requested function was unavailable; no action completed."},
            {"type": "finish", "reason": "stop"},
        ]
    )
    bot = Bot(scripts)
    install_fakes(bot)
    events = asyncio.run(_drain(ChatTurnService(runtime).stream_chat_turn("perform a task", "closing")))
    assert bot.call_count == MAX_TOOL_LOOPS + 1
    assert requests[-1]["tools"] is None
    assert any(e.type == "text" and "no action completed" in e.content for e in events)
    assert not any(e.type == "error" for e in events)


def test_unknown_tool_outcome_stops_retries_and_requests_summary(runtime, install_fakes, monkeypatch):
    from yumi.core.platform.dispatch import ToolDispatcher
    from yumi.core.platform.dispatch.context import ToolResult
    from yumi.core.platform.tools.tool import TOOL_REGISTRY

    name = "review_timeout_tool"
    monkeypatch.setitem(
        TOOL_REGISTRY,
        name,
        {
            "callable": lambda: None,
            "schema": {
                "type": "function",
                "function": {"name": name, "parameters": {"type": "object", "properties": {}}},
            },
        },
    )
    executions = []

    async def run_all(self, invocations, ctx):
        executions.extend(invocations)
        return [ToolResult(func_name=name, status="unknown", result="Timed out; outcome unknown") for _ in invocations]

    monkeypatch.setattr(ToolDispatcher, "run_all", run_all)
    requests = []

    class Bot(_FakeBot):
        async def chat_stream(self, **kwargs):
            requests.append(kwargs)
            async for chunk in super().chat_stream(**kwargs):
                yield chunk

    bot = Bot(
        [
            [{"type": "tool_call", "tool_calls": [{"id": "c1", "function": {"name": name, "arguments": {}}}]}],
            [{"type": "text", "content": "The outcome is unknown."}, {"type": "finish", "reason": "stop"}],
        ]
    )
    install_fakes(bot)
    events = asyncio.run(_drain(ChatTurnService(runtime).stream_chat_turn("perform a task", "unknown")))
    assert len(executions) == 1
    assert requests[-1]["tools"] is None
    assert any(e.type == "text" and "unknown" in e.content for e in events)


def test_usage_recorded_on_tool_call_turns(runtime, install_fakes, monkeypatch):
    """Regression: usage emitted before the tool_call signal must be recorded.

    Providers yield ``usage`` ahead of ``tool_call`` precisely because the
    consumer stops on tool_call; if that order regressed, tool-call turns would
    silently under-count tokens.
    """
    import yumi.core.platform.dispatch.usage as usage_mod

    captured: dict = {}

    def fake_record(*, session_id, prompt_tokens, completion_tokens, model):  # noqa: ARG001
        captured["pt"] = prompt_tokens
        captured["ct"] = completion_tokens

    monkeypatch.setattr(usage_mod, "record_tool_routing_usage", fake_record)

    per_iter = [
        {"type": "usage", "prompt_tokens": 10, "completion_tokens": 4, "model": "fake-model"},
        {"type": "tool_call", "tool_calls": [{"id": "c0", "function": {"name": "nope_tool", "arguments": "{}"}}]},
    ]
    bot = _FakeBot(scripted_chunks=[per_iter for _ in range(MAX_TOOL_LOOPS + 2)])
    install_fakes(bot)

    svc = ChatTurnService(runtime)
    asyncio.run(_drain(svc.stream_chat_turn("hi", "s_usage")))
    assert captured.get("pt", 0) > 0  # tokens from tool-call turns were recorded


def test_persist_tool_ephemeral_spans_persists_every_completed_tool_turn():
    messages = [
        {"role": "system", "content": "ambient"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call-first", "function": {"name": "first", "arguments": {}}}],
        },
        {"role": "tool", "tool_call_id": "call-first", "content": "one", "name": "first"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "call-second", "function": {"name": "second", "arguments": {}}}],
        },
        {"role": "tool", "tool_call_id": "call-second", "content": "two", "name": "second"},
    ]
    persisted = []

    class _Mem:
        def persist_openai_messages(self, turn):
            persisted.append(turn)

    class _Bot:
        def session_memory(self, _session_id):
            return _Mem()

    _persist_tool_ephemeral_spans(messages, "s_multi_tool", _Bot())

    assert [[row["role"] for row in turn] for turn in persisted] == [["assistant", "tool"], ["assistant", "tool"]]
    assert persisted[0][0]["tool_calls"][0]["function"]["name"] == "first"
    assert persisted[0][1]["tool_call_id"] == "call-first"
    assert persisted[1][0]["tool_calls"][0]["function"]["name"] == "second"
    assert persisted[1][1]["tool_call_id"] == "call-second"
    assert messages == [{"role": "system", "content": "ambient"}]


def test_normalize_exhausted_emits_error(runtime, install_fakes):
    """Malformed tool_calls force the normalizer past its retry budget."""
    bad_chunk = [{"type": "tool_call", "tool_calls": [{"garbage": True}]}]
    scripts = [bad_chunk for _ in range(10)]
    bot = _FakeBot(scripted_chunks=scripts)
    install_fakes(bot)

    svc = ChatTurnService(runtime)
    events = asyncio.run(_drain(svc.stream_chat_turn("hi", "s3")))
    errs = [e for e in events if getattr(e, "type", None) == "error"]
    assert errs, "expected error after normalize retries exhausted"
    assert any("could not be parsed" in e.content for e in errs)


def test_owner_mismatch_yields_forbidden(runtime, install_fakes, monkeypatch):
    """Non-single-user identity that doesn't own the session must hit FORBIDDEN."""
    bot = _FakeBot(scripted_chunks=[[{"type": "text", "content": "hi"}]])
    install_fakes(bot)

    import yumi.core.features.chat.service as svc_mod

    class _Scope:
        def owner_user_from_session_id(self, _sid: str) -> str:
            return "someone_else"

    monkeypatch.setattr(svc_mod, "get_session_scope", lambda: _Scope())

    fake_identity = Identity(user_id="me", scopes=("user",), source="plugin")
    monkeypatch.setattr(svc_mod, "get_current_identity", lambda: fake_identity)

    service = ChatTurnService(runtime)
    events = asyncio.run(_drain(service.stream_chat_turn("hi", "s4")))
    forbid = [e for e in events if getattr(e, "type", None) == "error" and getattr(e, "code", None) == "FORBIDDEN"]
    assert forbid, f"expected FORBIDDEN error, got {events!r}"


def test_class1_context_tool_prefetched_and_injected(runtime, install_fakes):
    """A class-1 (proactive_context) tool runs before generation, and its result
    is injected as an ephemeral context note passed to the model that turn."""
    from yumi.core.platform.tools.tool import TOOL_REGISTRY, register_tool

    calls = {"n": 0}

    def get_user_context() -> str:
        calls["n"] += 1
        return "mood=great; plan=ship v1"

    register_tool(get_user_context, "Current user context", proactive_context=True)

    captured: dict = {}

    class _CapBot(_FakeBot):
        async def chat_stream(self, **kwargs):
            captured["ephemeral"] = kwargs.get("ephemeral_messages")
            async for c in super().chat_stream(**kwargs):
                yield c

    try:
        bot = _CapBot(scripted_chunks=[[{"type": "text", "content": "hi"}]])
        install_fakes(bot)

        svc = ChatTurnService(runtime)
        asyncio.run(_drain(svc.stream_chat_turn("hello", "s_ctx")))

        assert calls["n"] == 1, "context tool should be prefetched once per turn"
        eph = captured.get("ephemeral") or []
        joined = "\n".join(m.get("content", "") for m in eph if isinstance(m, dict))
        assert "mood=great; plan=ship v1" in joined, f"context not injected: {eph!r}"
    finally:
        TOOL_REGISTRY.pop("get_user_context", None)


def test_turn_language_note_injected_from_latest_prompt(runtime, install_fakes):
    captured: dict = {}

    class _CapBot(_FakeBot):
        async def chat_stream(self, **kwargs):
            captured["ephemeral"] = kwargs.get("ephemeral_messages")
            async for c in super().chat_stream(**kwargs):
                yield c

    bot = _CapBot(scripted_chunks=[[{"type": "text", "content": "おやすみ"}]])
    install_fakes(bot)

    svc = ChatTurnService(runtime)
    asyncio.run(_drain(svc.stream_chat_turn("疲れた、めっちゃ眠い", "s_lang")))

    eph = captured.get("ephemeral") or []
    joined = "\n".join(m.get("content", "") for m in eph if isinstance(m, dict))
    assert "[Turn language]" in joined
    assert "suggests Japanese" in joined
    assert "most natural" in joined
    assert "MUST be in Japanese" not in joined
