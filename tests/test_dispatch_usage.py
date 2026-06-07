"""UsageRecorder: token accumulation + on-exit recording hook."""

from __future__ import annotations

import yumi.core.platform.dispatch.usage as usage_mod
from yumi.core.platform.dispatch.context import TurnContext
from yumi.core.platform.dispatch.usage import UsageRecorder


def _ctx() -> TurnContext:
    return TurnContext(prompt="hi", session_id="s1")


def test_add_accumulates_tokens_and_model():
    rec = UsageRecorder(_ctx())
    rec.add({"prompt_tokens": 10, "completion_tokens": 4, "model": "m1"})
    rec.add({"prompt_tokens": 7, "completion_tokens": 2})
    assert rec.total_prompt_tokens == 17
    assert rec.total_completion_tokens == 6
    assert rec.usage_model == "m1"


def test_add_handles_missing_fields():
    rec = UsageRecorder(_ctx())
    rec.add({})
    rec.add({"prompt_tokens": None, "completion_tokens": None})
    assert rec.total_prompt_tokens == 0
    assert rec.total_completion_tokens == 0


def test_exit_calls_record_tool_routing_usage(monkeypatch):
    captured: dict = {}

    def fake_record(*, session_id, prompt_tokens, completion_tokens, model):
        captured["sid"] = session_id
        captured["pt"] = prompt_tokens
        captured["ct"] = completion_tokens
        captured["model"] = model

    monkeypatch.setattr(usage_mod, "record_tool_routing_usage", fake_record)

    rec = UsageRecorder(_ctx())
    rec.add({"prompt_tokens": 3, "completion_tokens": 1, "model": "m2"})
    with rec:
        pass
    assert captured == {"sid": "s1", "pt": 3, "ct": 1, "model": "m2"}


def test_context_manager_swallows_record_failures(monkeypatch):
    def boom(**_):
        raise RuntimeError("downstream broke")

    monkeypatch.setattr(usage_mod, "record_tool_routing_usage", boom)
    rec = UsageRecorder(_ctx())
    with rec:
        pass  # should not raise
