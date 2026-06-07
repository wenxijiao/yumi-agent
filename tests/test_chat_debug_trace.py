"""Tests for per-session chat NDJSON tracing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from kumi.core.api.chat_debug_trace import (
    append_stream_event,
    append_turn_begin,
    start_trace,
    stop_trace,
)


def test_chat_trace_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kumi.core.api.chat_debug_trace.debug_dir", lambda: str(tmp_path))
    sid = "tg_12345"
    p = start_trace(sid)
    assert Path(p).is_file()
    append_turn_begin(sid, prompt="hello", think=False, timer_callback=False)
    append_stream_event(sid, {"type": "text", "content": "hi"})
    end_p = stop_trace(sid)
    assert end_p == p
    lines = Path(p).read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) >= 3
    rows = [json.loads(line) for line in lines]
    assert rows[0]["kind"] == "meta" and rows[0]["action"] == "start"
    assert any(r.get("kind") == "turn_begin" and r.get("prompt") == "hello" for r in rows)
    assert any(r.get("kind") == "stream_event" and r.get("event", {}).get("content") == "hi" for r in rows)
    assert rows[-1]["kind"] == "meta" and rows[-1]["action"] == "end"


def test_start_trace_idempotent_returns_same_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("kumi.core.api.chat_debug_trace.debug_dir", lambda: str(tmp_path))
    sid = "line_ab"
    a = start_trace(sid)
    b = start_trace(sid)
    assert a == b
    stop_trace(sid)
