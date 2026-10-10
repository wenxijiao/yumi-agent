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


@pytest.mark.parametrize(
    ("payload", "silent"),
    [
        ({"ok": True, "playback": {"state": "paused"}}, True),
        ({"ok": False, "error": "failed"}, False),
        ({"ok": True, "error": "incomplete"}, False),
        ({"ok": "true"}, False),
        ("Error executing player", False),
    ],
)
def test_registered_terminal_tool_ends_without_extra_model_round(runtime, install_fakes, monkeypatch, payload, silent):
    from yumi.core.platform.tools.tool import TOOL_REGISTRY, register_tool

    name = "terminal_playback_test"
    monkeypatch.setitem(TOOL_REGISTRY, name, {})
    register_tool(lambda: payload, "Play a track", name=name, reply_on_success=False)
    bot = _FakeBot(
        [
            [{"type": "tool_call", "tool_calls": [{"id": "play", "function": {"name": name, "arguments": {}}}]}],
            [{"type": "text", "content": "Feedback required"}],
        ]
    )
    install_fakes(bot)
    events = asyncio.run(_drain(ChatTurnService(runtime).stream_chat_turn("play music", "silent-tool")))
    completion = [e for e in events if e.type == "turn_complete"]
    assert bool(completion) is silent
    assert bot.call_count == (1 if silent else 2)
    if silent:
        assert completion[0].voice_capture == "pause"
        assert completion[0].reply == "none"
        assert not any(e.type == "text" for e in events)


@pytest.mark.parametrize("second_kind", ["normal", "missing", "silent"])
def test_terminal_tool_does_not_hide_other_results_or_missing_calls(runtime, install_fakes, monkeypatch, second_kind):
    from yumi.core.platform.tools.tool import TOOL_REGISTRY, register_tool

    ran = []
    for name, reply in [("terminal_first", False), ("terminal_second", second_kind == "normal")]:
        monkeypatch.setitem(TOOL_REGISTRY, name, {})
        if name == "terminal_second" and second_kind == "missing":
            monkeypatch.delitem(TOOL_REGISTRY, name)
            continue

        def call(name=name):
            ran.append(name)
            return {"ok": True}

        register_tool(call, "Test", name=name, reply_on_success=reply)
    bot = _FakeBot(
        [
            [
                {
                    "type": "tool_call",
                    "tool_calls": [
                        {"id": name, "function": {"name": name, "arguments": {}}}
                        for name in ["terminal_first", "terminal_second"]
                    ],
                }
            ],
            [{"type": "text", "content": "Other result or missing action"}],
        ]
    )
    install_fakes(bot)
    events = asyncio.run(_drain(ChatTurnService(runtime).stream_chat_turn("do both", "silent-batch")))
    assert bool([e for e in events if e.type == "turn_complete"]) == (second_kind == "silent")
    assert set(ran) == ({"terminal_first"} if second_kind == "missing" else {"terminal_first", "terminal_second"})


@pytest.mark.parametrize("readiness", ["legacy", "ready", "unready", "timeout"])
@pytest.mark.parametrize("music_tool", ["music_play", "music_play_request"])
def test_music_completion_persists_monitor_for_the_executed_edge(
    runtime, install_fakes, monkeypatch, readiness, music_tool
):
    from yumi.core.features.chat import media_prepare
    from yumi.core.platform.observability.turn_inspector import get_turn
    from yumi.core.platform.plugins import get_current_identity
    from yumi.core.platform.runtime.assistant_context import message_media
    from yumi.core.platform.runtime.edge_naming import edge_tool_key_prefix

    prefix = edge_tool_key_prefix("Room")
    played = []
    acknowledged = []
    monkeypatch.setattr(media_prepare, "PREPARE_TIMEOUT", 0.01)

    class Peer:
        async def send_json(self, frame):
            assert frame["name"] == music_tool
            assert readiness == "legacy" or acknowledged == [True]
            played.append(True)
            runtime.edge_registry.pending_tool_calls[frame["call_id"]]["future"].set_result(
                '{"ok":true,"playback":{"state":"paused"}}'
            )

    runtime.edge_registry.active_connections["Room"] = Peer()
    runtime.edge_registry.tools["Room"] = {
        prefix + name: {
            "reply_on_success": name != music_tool,
            "schema": {
                "type": "function",
                "function": {"name": prefix + name, "parameters": {"type": "object", "properties": {}}},
            },
        }
        for name in [music_tool, "music_status"]
    }
    bot = _FakeBot(
        [
            [
                {
                    "type": "tool_call",
                    "tool_calls": [{"id": "play", "function": {"name": prefix + music_tool, "arguments": {}}}],
                }
            ]
        ]
    )
    install_fakes(bot)

    async def run():
        token = message_media.set({"prepare_media_output": readiness != "legacy"})
        events = []
        try:
            async for event in ChatTurnService(runtime).stream_chat_turn("play", "music-monitor"):
                events.append(event)
                if event.type == "media_prepare":
                    assert not played
                    if readiness != "timeout":
                        acknowledged.append(readiness == "ready")
                        media_prepare.acknowledge(get_current_identity().user_id, event.preparation_id, acknowledged[0])
            assert not media_prepare._pending
            return events
        finally:
            message_media.reset(token)

    events = asyncio.run(run())
    if readiness in {"unready", "timeout"}:
        assert not played
        assert any(e.type == "error" and e.code == "MEDIA_OUTPUT_NOT_READY" for e in events)
        assert not any(e.type == "turn_complete" for e in events)
        assert bot.call_count == 1
        return
    completion = next(e for e in events if e.type == "turn_complete")
    assert completion.media_watch == completion.turn_id
    assert get_turn(completion.turn_id)["media_watch"] == {"edge": "Room", "tool": prefix + "music_status"}
    assert bot.call_count == 1


def test_happy_path_text_only_stream(runtime, install_fakes):
    bot = _FakeBot(scripted_chunks=[[{"type": "text", "content": "hello"}]])
    install_fakes(bot)

    svc = ChatTurnService(runtime)
    events = asyncio.run(_drain(svc.stream_chat_turn("hi", "s1")))
    text_events = [e for e in events if getattr(e, "type", None) == "text"]
    assert any(e.content == "hello" for e in text_events)
    assert bot.call_count == 1


def test_context_and_tool_selection_prepare_concurrently(runtime, install_fakes, monkeypatch):
    bot = _FakeBot(scripted_chunks=[[{"type": "text", "content": "hello"}]])
    install_fakes(bot)

    async def run():
        context_started, routing_started = asyncio.Event(), asyncio.Event()

        async def prefetch(self, ctx):
            context_started.set()
            await routing_started.wait()
            return None

        async def select(self, ctx, query):
            routing_started.set()
            await context_started.wait()
            return None

        monkeypatch.setattr(ChatTurnService, "_prefetch_runtime_context", prefetch)
        monkeypatch.setattr(ChatTurnService, "_select_tools", select)
        return await asyncio.wait_for(_drain(ChatTurnService(runtime).stream_chat_turn("hello", "overlap")), 1)

    events = asyncio.run(run())
    assert bot.call_count == 1
    assert not any(e.type == "error" for e in events)


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


def test_browse_activates_tools_in_the_next_model_request(runtime, install_fakes, monkeypatch):
    """Exercise actual local dispatch -> activation result -> next provider tools."""
    from types import SimpleNamespace

    import yumi.core.features.chat.service as service
    from yumi.core.platform.tools import routing, tool
    from yumi.tools import edge_discovery_tools as discovery

    registry = {}
    monkeypatch.setattr(tool, "TOOL_REGISTRY", registry)
    monkeypatch.setattr(routing, "TOOL_REGISTRY", registry)
    monkeypatch.setattr("yumi.core.platform.dispatch.dispatcher.TOOL_REGISTRY", registry)
    tool.register_tool(discovery.browse_app_tools, "Browse visible tools")
    monkeypatch.setattr(discovery, "get_default_runtime", lambda: runtime)
    name = "edge_room__music_play"
    runtime.edge_registry.tools["room"] = {
        name: {
            "schema": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": "Play a song",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        }
    }
    requests = []

    class Bot(_FakeBot):
        async def chat_stream(self, **kwargs):
            requests.append(kwargs)
            async for chunk in super().chat_stream(**kwargs):
                yield chunk

    bot = Bot(
        [
            [
                {
                    "type": "tool_call",
                    "tool_calls": [
                        {"id": "browse1", "function": {"name": "browse_app_tools", "arguments": {"device": "room"}}}
                    ],
                }
            ],
            [{"type": "text", "content": "Found the music tool."}],
        ]
    )
    install_fakes(bot)
    monkeypatch.setattr(
        service, "select_tool_schemas", lambda **kw: SimpleNamespace(tools=[registry["browse_app_tools"]["schema"]])
    )
    events = asyncio.run(_drain(ChatTurnService(runtime).stream_chat_turn("play a song", "browse-integration")))
    assert len(requests) == 2
    assert name not in {s["function"]["name"] for s in requests[0]["tools"]}
    assert name in {s["function"]["name"] for s in requests[1]["tools"]}
    assert not any(e.type == "error" for e in events)

    # On a later turn, a large catalog must not force the model to browse again
    # for this already-discovered function, even for an implicit follow-up.
    from yumi.core.features.config import ModelConfig

    cfg = ModelConfig(edge_tools_routing_mode="on_demand", embedding_model=None)
    monkeypatch.setattr(routing, "load_model_config", lambda: cfg)
    monkeypatch.setattr(service, "select_tool_schemas", routing.select_tool_schemas)
    for i in range(80):
        noise = f"edge_factory__calibrate_{i}"
        runtime.edge_registry.tools.setdefault("factory", {})[noise] = {
            "schema": {
                "type": "function",
                "function": {
                    "name": noise,
                    "description": "Calibrate factory pressure sensors. " * 10,
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        }
    bot._calls = [[{"type": "text", "content": "Ready."}]]
    events = asyncio.run(_drain(ChatTurnService(runtime).stream_chat_turn("再来一次", "browse-integration")))
    assert len(requests) == 3
    assert name in {s["function"]["name"] for s in requests[2]["tools"]}
    assert not any(e.type == "error" for e in events)


def test_voice_end_tool_emits_standby_without_pausing_wake_or_another_model_round(runtime, install_fakes, monkeypatch):
    from yumi.core.platform.runtime.assistant_context import message_media
    from yumi.core.platform.tools.tool import TOOL_REGISTRY, register_tool
    from yumi.tools.voice_tools import end_voice_conversation

    name = "end_voice_conversation"
    monkeypatch.setitem(TOOL_REGISTRY, name, {})
    register_tool(end_voice_conversation, "End voice", reply_on_success=False)
    bot = _FakeBot(
        [[{"type": "tool_call", "tool_calls": [{"id": "end", "function": {"name": name, "arguments": {}}}]}]]
    )
    install_fakes(bot)

    async def run():
        token = message_media.set({"voice_session_controls": True})
        try:
            events = await _drain(ChatTurnService(runtime).stream_chat_turn("I need to leave now", "voice-end"))
            assert [e.type for e in events].count("voice_standby") == 1
            assert not any(e.type in {"turn_complete", "text", "error"} for e in events)
            assert bot.call_count == 1
        finally:
            message_media.reset(token)

    asyncio.run(run())
