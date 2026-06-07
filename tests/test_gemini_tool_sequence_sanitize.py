"""_sanitize_gemini_tool_sequence must drop orphan tool rows (Gemini 400 on bad ordering)."""

import base64
import json
from pathlib import Path

import pytest
from kumi.core.providers.diagnostics import write_provider_failure_diagnostic
from kumi.core.providers.gemini_provider import (
    GeminiProvider,
    _sanitize_gemini_tool_sequence,
)
from kumi.core.tool_call_normalize import normalize_tool_calls

_SIG = base64.b64encode(b"gemini-thought-signature").decode("ascii")


def test_drops_tool_rows_after_system_when_window_starts_mid_turn():
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "system", "content": "Extra context."},
        {"role": "tool", "name": "lights", "content": '{"on": true}'},
        {"role": "user", "content": "[12:00] Timer fired"},
    ]
    out = _sanitize_gemini_tool_sequence(messages)
    assert [m.get("role") for m in out] == ["system", "system", "user"]


def test_keeps_paired_assistant_tool_block():
    messages = [
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "1", "function": {"name": "ping", "arguments": "{}"}, "thought_signature": _SIG}],
        },
        {"role": "tool", "name": "ping", "content": "pong"},
        {"role": "user", "content": "thanks"},
    ]
    out = _sanitize_gemini_tool_sequence(messages)
    assert len(out) == 4
    assert out[1]["role"] == "assistant" and out[1].get("tool_calls")
    assert out[2]["role"] == "tool"


def test_drops_incomplete_assistant_tool_calls_tail():
    messages = [
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "1", "function": {"name": "a", "arguments": "{}"}, "thought_signature": _SIG},
                {"id": "2", "function": {"name": "b", "arguments": "{}"}, "thought_signature": _SIG},
            ],
        },
        {"role": "tool", "name": "a", "content": "1"},
        {"role": "user", "content": "next"},
    ]
    out = _sanitize_gemini_tool_sequence(messages)
    assert [m.get("role") for m in out] == ["user", "user"]


def test_drops_assistant_tool_block_without_gemini_thought_signature():
    messages = [
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "1", "function": {"name": "ping", "arguments": "{}"}}],
        },
        {"role": "tool", "name": "ping", "content": "pong"},
        {"role": "user", "content": "next"},
    ]

    out = _sanitize_gemini_tool_sequence(messages)
    assert [m.get("role") for m in out] == ["user", "user"]


def test_drops_tool_call_block_when_window_starts_after_only_system_rows():
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "system", "content": "Relevant memory."},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "1", "function": {"name": "ping", "arguments": "{}"}, "thought_signature": _SIG}],
        },
        {"role": "tool", "name": "ping", "content": "pong"},
        {"role": "user", "content": "morning"},
    ]

    out = _sanitize_gemini_tool_sequence(messages)

    assert [m.get("role") for m in out] == ["system", "system", "user"]


def test_keeps_tool_call_after_assistant_text_when_merged_turn_follows_user():
    messages = [
        {"role": "user", "content": "play it again"},
        {"role": "assistant", "content": "Sure, I will play it again."},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "1", "function": {"name": "play", "arguments": "{}"}, "thought_signature": _SIG}],
        },
        {"role": "tool", "name": "play", "content": "ok"},
        {"role": "user", "content": "thanks"},
    ]

    out = _sanitize_gemini_tool_sequence(messages)

    assert [m.get("role") for m in out] == ["user", "assistant", "assistant", "tool", "user"]


def test_normalize_preserves_gemini_thought_signature():
    out = normalize_tool_calls([{"function": {"name": "ping", "arguments": {}}, "thought_signature": _SIG}])
    assert out[0]["thought_signature"] == _SIG


def test_build_contents_replays_gemini_thought_signature():
    pytest.importorskip("google.genai")
    provider = GeminiProvider.__new__(GeminiProvider)
    _, contents = provider._build_contents(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {"name": "ping", "arguments": {}},
                        "thought_signature": _SIG,
                    }
                ],
            }
        ]
    )

    part = contents[0].parts[0]
    assert part.thought_signature == base64.b64decode(_SIG)


def test_gemini_failure_diagnostic_captures_turn_order_context(monkeypatch, tmp_path):
    pytest.importorskip("google.genai")
    monkeypatch.setenv("KUMI_DEBUG_DIR", str(tmp_path))
    messages = [
        {"role": "user", "content": "go"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "ping", "arguments": "{}"}, "thought_signature": _SIG}],
        },
        {"role": "tool", "name": "ping", "content": "pong"},
    ]
    provider = GeminiProvider.__new__(GeminiProvider)
    system_instruction, contents = provider._build_contents(messages)

    path = write_provider_failure_diagnostic(
        exc=RuntimeError("400 INVALID_ARGUMENT"),
        provider="gemini",
        model="gemini-test",
        messages=messages,
        tools=[{"function": {"name": "ping", "description": "Ping tool", "parameters": {"properties": {}}}}],
        extra={
            "system_instruction_preview": system_instruction,
            "gemini_contents": [
                {"role": c.role, "parts": [{"type": "function_response"} for p in c.parts if p.function_response]}
                for c in contents
            ],
        },
    )

    assert path is not None
    payload = json.loads(tmp_path.joinpath(Path(path).name).read_text(encoding="utf-8"))
    assert payload["provider"] == "gemini"
    assert payload["error"]["message"] == "400 INVALID_ARGUMENT"
    assert payload["messages"][1]["tool_calls"][0]["has_thought_signature"] is True
    part_types = [p["type"] for c in payload["extra"]["gemini_contents"] for p in c["parts"]]
    assert "function_response" in part_types
