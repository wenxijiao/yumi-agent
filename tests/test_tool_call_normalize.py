"""Tests for tool call normalization (Ollama / SDK objects → plain dicts)."""

from __future__ import annotations

import json

from kumi.core.platform.tools.normalize import (
    normalize_tool_calls,
    tool_call_format_retry_user_content,
)


def test_normalize_openai_style_dict():
    raw = [{"id": "c1", "type": "function", "function": {"name": "foo", "arguments": '{"a": 1}'}}]
    out = normalize_tool_calls(raw)
    assert len(out) == 1
    assert out[0]["function"]["name"] == "foo"
    assert out[0]["function"]["arguments"] == {"a": 1}


def test_normalize_dict_arguments_already_object():
    raw = [{"function": {"name": "bar", "arguments": {"x": "y"}}}]
    out = normalize_tool_calls(raw)
    assert out[0]["function"]["arguments"] == {"x": "y"}


class _FakeFunction:
    def __init__(self, name: str, arguments):
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, name: str, arguments):
        self.function = _FakeFunction(name, arguments)
        self.id = "call-1"
        self.type = "function"


def test_normalize_ollama_like_objects():
    tcalls = [_FakeToolCall("set_light", {"room": "kitchen", "on": True})]
    out = normalize_tool_calls(tcalls)
    assert len(out) == 1
    assert out[0]["function"]["name"] == "set_light"
    assert out[0]["function"]["arguments"] == {"room": "kitchen", "on": True}
    assert out[0]["id"] == "call-1"
    json.dumps(out)  # must be JSON-serializable


def test_normalize_mixed_dict_and_object():
    tcalls = [
        {"function": {"name": "a", "arguments": "{}"}},
        _FakeToolCall("b", {}),
    ]
    out = normalize_tool_calls(tcalls)
    assert [x["function"]["name"] for x in out] == ["a", "b"]


def test_normalize_invalid_returns_empty():
    assert normalize_tool_calls([{"function": "not-a-dict"}]) == []
    assert normalize_tool_calls(None) == []
    assert normalize_tool_calls(object()) == []


def test_normalize_rejects_empty_tool_name():
    assert normalize_tool_calls([{"function": {"name": "", "arguments": {}}}]) == []


def test_tool_call_format_retry_user_content_includes_diagnosis():
    raw = [{"function": {"name": "", "arguments": {}}}]
    msg = tool_call_format_retry_user_content(raw)
    assert "Diagnosis:" in msg
    assert "function.name" in msg
    assert "Kumi" in msg
