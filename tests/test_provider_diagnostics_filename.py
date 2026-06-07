"""Diagnostic log filenames include UTC time, provider, phase, model, and error hint."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from kumi.core.providers.diagnostics import (
    build_provider_diagnostic_filename,
    write_chat_diagnostic,
    write_chat_loop_diagnostic,
)


def test_diagnostic_filename_includes_stamp_provider_phase_model_hint():
    fixed = datetime(2026, 5, 4, 12, 23, 56, tzinfo=timezone.utc)
    name = build_provider_diagnostic_filename(
        provider="gemini",
        phase="chat_stream",
        exc=RuntimeError("400 INVALID_ARGUMENT. something"),
        model="gemini-3-flash-preview",
        now=fixed,
        unique_suffix_len=8,
    )
    assert name.startswith("20260504T122356Z_gemini_chat_stream_gemini-3-flash-preview_")
    assert "INVALID_ARGUMENT" in name
    assert name.endswith(".json")
    assert len(name.rsplit("_", 1)[-1].removesuffix(".json")) == 8


def test_diagnostic_filename_optional_note():
    fixed = datetime(2026, 5, 3, 0, 0, 0, tzinfo=timezone.utc)
    name = build_provider_diagnostic_filename(
        provider="openai",
        phase="chat_stream_text_only_fallback",
        exc=ValueError("rate limited"),
        note="vision-retry",
        now=fixed,
        unique_suffix_len=6,
    )
    assert name.startswith("20260503T000000Z_openai_chat_stream_text_only_fallback_")
    assert "rate-limited" in name
    assert "vision-retry" in name


def test_chat_loop_diagnostic_captures_tools_and_events(monkeypatch, tmp_path):
    monkeypatch.setenv("KUMI_DEBUG_DIR", str(tmp_path))

    path = write_chat_loop_diagnostic(
        session_id="tg_1",
        prompt="我听困了，可以都关掉吗我想睡觉了",
        model="test-model",
        loop_count=10,
        messages=[
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "set_light", "arguments": {}}}]},
            {"role": "tool", "name": "set_light", "content": "Error: Tool not registered."},
        ],
        tools=[{"function": {"name": "get_weather", "description": "Get weather", "parameters": {"properties": {}}}}],
        extra={"reason": "maximum_tool_execution_iterations"},
    )

    assert path is not None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assert payload["phase"] == "chat_tool_loop"
    assert payload["session_id"] == "tg_1"
    assert payload["loop_count"] == 10
    assert payload["prompt_preview"] == "我听困了，可以都关掉吗我想睡觉了"
    assert payload["tools"][0]["name"] == "get_weather"
    assert payload["messages"][0]["tool_calls"][0]["name"] == "set_light"
    assert payload["extra"]["reason"] == "maximum_tool_execution_iterations"


def test_chat_diagnostic_captures_generic_errors(monkeypatch, tmp_path):
    monkeypatch.setenv("KUMI_DEBUG_DIR", str(tmp_path))

    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        path = write_chat_diagnostic(
            phase="chat_pipeline_failed",
            session_id="web_1",
            prompt="hello",
            model="test-model",
            messages=[{"role": "user", "content": "hello"}],
            tools=[{"function": {"name": "web_search", "description": "Search", "parameters": {"properties": {}}}}],
            error=exc,
            extra={"reason": "exception"},
        )

    assert path is not None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    assert payload["phase"] == "chat_pipeline_failed"
    assert payload["error"]["type"] == "RuntimeError"
    assert payload["error"]["message"] == "boom"
    assert payload["tools"][0]["name"] == "web_search"
    assert payload["messages"][0]["role"] == "user"
