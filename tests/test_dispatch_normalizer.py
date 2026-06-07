"""ToolCallNormalizer: retry budget, ready/retry/exhausted outcomes."""

from __future__ import annotations

from yumi.core.platform.dispatch.context import TurnContext
from yumi.core.platform.dispatch.normalizer import ToolCallNormalizer, summarize_tool_args


def _ctx() -> TurnContext:
    return TurnContext(prompt="hi", session_id="s1")


def _good_tcall(name: str = "echo", args: str = '{"x":1}') -> dict:
    return {"id": "c1", "function": {"name": name, "arguments": args}}


def test_normalize_ready_resets_retry_count():
    ctx = _ctx()
    ctx.tool_format_retries = 2
    n = ToolCallNormalizer(max_retries=3)
    out = n.normalize([_good_tcall()], ctx)
    assert out.kind == "ready"
    assert out.tcalls and out.tcalls[0]["function"]["name"] == "echo"
    assert ctx.tool_format_retries == 0


def test_normalize_retry_increments_and_pushes_hint():
    ctx = _ctx()
    n = ToolCallNormalizer(max_retries=3)
    out = n.normalize([{"garbage": True}], ctx)
    assert out.kind == "retry"
    assert out.retry_attempt == 1
    assert ctx.tool_format_retries == 1
    assert ctx.ephemeral_messages and ctx.ephemeral_messages[-1]["role"] == "user"
    assert any(ev.get("reason") == "invalid_tool_call_format" for ev in ctx.tool_loop_events)


def test_normalize_exhausted_after_max_retries():
    ctx = _ctx()
    n = ToolCallNormalizer(max_retries=2)
    for _ in range(2):
        out = n.normalize([{"bad": True}], ctx)
        assert out.kind == "retry"
    out = n.normalize([{"bad": True}], ctx)
    assert out.kind == "exhausted"
    assert ctx.tool_format_retries == 3


def test_summarize_tool_args_truncates():
    s = summarize_tool_args({"x": "a" * 1000}, max_len=50)
    assert len(s) <= 53
    assert s.endswith("...")


def test_summarize_tool_args_empty():
    assert summarize_tool_args(None) == "{}"
    assert summarize_tool_args({}) == "{}"
