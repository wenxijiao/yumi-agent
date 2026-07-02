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


def test_max_tool_loops_emits_error(runtime, install_fakes):
    """Looping ``unknown tool`` calls drives loop_count past MAX_TOOL_LOOPS."""
    chunks_per_iter = [
        {
            "type": "tool_call",
            "tool_calls": [{"id": "c0", "function": {"name": "nope_tool", "arguments": "{}"}}],
        }
    ]
    scripts = [chunks_per_iter for _ in range(MAX_TOOL_LOOPS + 2)]
    bot = _FakeBot(scripted_chunks=scripts)
    install_fakes(bot)

    svc = ChatTurnService(runtime)
    events = asyncio.run(_drain(svc.stream_chat_turn("hi", "s2")))
    errs = [e for e in events if getattr(e, "type", None) == "error"]
    assert errs, "expected an error event after exhausting tool loops"
    assert any("Maximum tool execution iterations" in e.content for e in errs)
    assert bot.call_count == MAX_TOOL_LOOPS


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
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "first", "arguments": {}}}]},
        {"role": "tool", "tool_call_id": "call-first", "content": "one", "name": "first"},
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "second", "arguments": {}}}]},
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
