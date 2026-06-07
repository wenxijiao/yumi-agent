"""Unit tests for /chat NDJSON line format (no server)."""

import json

from kumi.core.api import stream_event


def test_stream_event_is_single_ndjson_line():
    line = stream_event("text", content="hello")
    assert line.endswith("\n")
    assert line.count("\n") == 1
    obj = json.loads(line.strip())
    assert obj == {"type": "text", "content": "hello"}


def test_stream_event_tool_status():
    line = stream_event("tool_status", status="running", content="…")
    obj = json.loads(line.strip())
    assert obj["type"] == "tool_status"
    assert obj["status"] == "running"
    assert obj["content"] == "…"
