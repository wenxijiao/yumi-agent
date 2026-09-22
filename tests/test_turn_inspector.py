"""Bounded chat-turn inspector store and debug HTTP contract."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from yumi.core.api import app
from yumi.core.features.chat.trace_sink import ChatTraceSink
from yumi.core.features.memory.memory import Memory
from yumi.core.platform.dispatch.context import TurnContext
from yumi.core.platform.observability.turn_inspector import (
    begin_turn,
    clear_turns,
    end_turn,
    get_turn,
    list_turns,
    record_finish,
    record_llm_request,
    record_routing,
    record_stream_event,
    record_tool_calls,
    record_tool_result,
    record_usage,
)


@pytest.fixture(autouse=True)
def _clean_turns():
    clear_turns()
    yield
    clear_turns()


def _begin(turn_id: str = "turn-1", session_id: str = "chat-1") -> None:
    begin_turn(
        turn_id=turn_id,
        session_id=session_id,
        prompt="查一下天气",
        think=False,
        timer_callback=False,
    )


def test_turn_inspector_captures_prompt_tools_usage_and_finish() -> None:
    _begin()
    record_routing(
        "chat-1",
        {
            "core_count": 2,
            "selected_edge_count": 1,
            "total_edge_count": 3,
            "elapsed_ms": 7,
        },
    )
    record_llm_request(
        "chat-1",
        provider="openai",
        model="gpt-test",
        messages=[
            {"role": "system", "content": "You are Yumi."},
            {"role": "system", "content": "Stable User Context:\n- likes tea"},
            {"role": "user", "content": "查一下天气"},
        ],
        tools=[
            {
                "type": "function",
                "function": {"name": "get_weather", "description": "Weather", "parameters": {}},
            }
        ],
    )
    record_usage(
        "chat-1",
        {
            "type": "usage",
            "prompt_tokens": 100,
            "completion_tokens": 12,
            "cached_prompt_tokens": 60,
            "model": "gpt-test",
        },
    )
    record_stream_event("chat-1", {"type": "text", "content": "今天晴天。"})
    record_finish("chat-1", {"type": "finish", "reason": "stop", "provider_reason": "stop"})
    end_turn(
        "chat-1",
        total_prompt_tokens=100,
        total_completion_tokens=12,
        usage_model="gpt-test",
    )

    summaries = list_turns(session_id="chat-1")
    assert len(summaries) == 1
    assert summaries[0]["cache_hit_percent"] == 60.0
    assert summaries[0]["trace_schema_version"] == 1
    assert summaries[0]["finish_reason"] == "stop"
    assert summaries[0]["response_preview"] == "今天晴天。"

    turn = get_turn("turn-1")
    assert turn is not None
    assert turn["trace_schema_version"] == 1
    assert [m["label"] for m in turn["rounds"][0]["messages"]] == [
        "Base system prompt",
        "Stable user context",
        "Current user message",
    ]
    assert turn["rounds"][0]["tool_names"] == ["get_weather"]
    assert turn["status"] == "complete"


def test_turn_inspector_groups_tool_call_and_result_into_round() -> None:
    _begin()
    record_llm_request(
        "chat-1",
        provider="claude",
        model="claude-test",
        messages=[{"role": "user", "content": "weather"}],
        tools=[],
    )
    calls = [{"id": "call-1", "function": {"name": "get_weather", "arguments": {"city": "Auckland"}}}]
    record_tool_calls("chat-1", loop=1, tool_calls=calls)
    record_tool_result(
        "chat-1",
        loop=1,
        call_id="call-1",
        tool="get_weather",
        resolved_tool="get_weather",
        kind="local",
        edge=None,
        status="success",
        duration_ms=25,
        result_preview="sunny",
    )
    end_turn("chat-1", total_prompt_tokens=0, total_completion_tokens=0, usage_model="claude-test")

    turn = get_turn("turn-1")
    assert turn is not None
    round_record = turn["rounds"][0]
    assert round_record["finish"]["reason"] == "tool_calls"
    assert round_record["tool_calls"][0]["function"]["name"] == "get_weather"
    assert round_record["tool_results"][0]["duration_ms"] == 25


def test_turn_inspector_preserves_inline_image_data_for_local_history() -> None:
    _begin()
    record_llm_request(
        "chat-1",
        provider="openai",
        model="vision",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "look"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64," + "A" * 100}},
                ],
            }
        ],
        tools=None,
    )
    turn = get_turn("turn-1")
    assert turn is not None
    content = turn["rounds"][0]["messages"][0]["content"]
    assert content[1]["image_url"]["url"].endswith("A" * 100)


def test_debug_turn_http_endpoints() -> None:
    _begin()
    end_turn("chat-1", total_prompt_tokens=0, total_completion_tokens=0, usage_model="")
    client = TestClient(app)

    listing = client.get("/debug/turns?session_id=chat-1").json()
    assert listing["turns"][0]["id"] == "turn-1"
    assert listing["retention"]["kind"] == "durable"

    detail = client.get("/debug/turns/turn-1").json()
    assert detail["turn"]["prompt"] == "查一下天气"
    assert client.get("/debug/turns/missing").status_code == 404


def test_chat_turn_endpoint_reads_durable_history(monkeypatch, tmp_path) -> None:
    memory = Memory(session_id="chat-1", storage_dir=tmp_path, max_recent=10)
    trace = {
        "id": "durable-turn",
        "session_id": "chat-1",
        "owner_user_id": "_local",
        "status": "complete",
        "started_at": "2026-08-02T01:02:03+00:00",
        "rounds": [],
        "timeline": [],
        "summary": {
            "id": "durable-turn",
            "session_id": "chat-1",
            "owner_user_id": "_local",
            "status": "complete",
            "started_at": "2026-08-02T01:02:03+00:00",
            "provider": "openai",
            "model": "gpt-test",
        },
    }
    memory.sqlite.upsert_turn_trace(trace, owner_user_id="_local")

    class Factory:
        def get_for_identity(self, _identity):
            return memory

    monkeypatch.setattr("yumi.core.features.chat.router.get_memory_factory", lambda: Factory())
    client = TestClient(app)

    listing = client.get("/chat/turns?session_id=chat-1").json()
    assert listing["turns"][0]["id"] == "durable-turn"
    assert client.get("/chat/turns/durable-turn").json()["turn"] == trace


def test_trace_sink_persists_completed_turn_to_session_sqlite(tmp_path) -> None:
    memory = Memory(session_id="chat-1", storage_dir=tmp_path, max_recent=10)

    class Bot:
        model_name = "gpt-test"

        def session_memory(self, _session_id):
            return memory

    ctx = TurnContext(prompt="hello", session_id="chat-1", owner_uid="_local")
    sink = ChatTraceSink(ctx, bot=Bot())
    sink.record_turn_begin()
    record_llm_request(
        "chat-1",
        provider="openai",
        model="gpt-test",
        messages=[{"role": "user", "content": "hello"}],
        tools=[],
    )
    sink.record_provider_finish({"type": "finish", "reason": "stop", "provider_reason": "stop"})
    sink.record_turn_end(total_prompt_tokens=5, total_completion_tokens=3, usage_model="gpt-test")

    stored = memory.sqlite.get_turn_trace(ctx.turn_id)
    assert stored is not None
    assert stored["trace_schema_version"] == 1
    assert stored["prompt"] == "hello"
    assert stored["summary"]["model"] == "gpt-test"


def test_activity_and_client_timing_require_owner_and_keep_first_observation(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from fastapi import HTTPException
    from yumi.core.features.chat import router

    memory = Memory(session_id="chat-1", storage_dir=tmp_path)
    _begin()
    record_llm_request(
        "chat-1", provider="test", model="test", messages=[{"role": "system", "content": "private prompt"}], tools=[]
    )
    record_stream_event("chat-1", {"type": "text", "content": "A reply"})
    trace = end_turn("chat-1", total_prompt_tokens=10, total_completion_tokens=2, usage_model="test")
    memory.sqlite.upsert_turn_trace(trace, owner_user_id="_local")
    monkeypatch.setattr(router, "get_memory_factory", lambda: SimpleNamespace(get_for_identity=lambda _: memory))
    client = TestClient(app)
    activity = client.get("/chat/turns/turn-1/activity")
    assert activity.status_code == 200
    assert activity.json()["rounds"][0]["response_text"] == "A reply"
    assert "private prompt" not in activity.text
    path = "/chat/turns/turn-1/timing"
    assert client.post(path, json={"first_text_ms": 120}).status_code == 200
    assert client.post(path, json={"first_text_ms": 999, "first_audio_ms": 500}).status_code == 200
    assert memory.sqlite.get_turn_trace("turn-1")["client_timing"] == {"first_text_ms": 120, "first_audio_ms": 500}
    assert client.post(path, json={"first_text_ms": -1}).status_code == 422

    def forbidden(*_):
        raise HTTPException(403, "Forbidden")

    monkeypatch.setattr(
        router, "get_session_scope", lambda: SimpleNamespace(ensure_session_owned_by_identity=forbidden)
    )
    assert client.get("/chat/turns/turn-1/activity").status_code == 403
    assert client.post(path, json={"first_text_ms": 42}).status_code == 403
