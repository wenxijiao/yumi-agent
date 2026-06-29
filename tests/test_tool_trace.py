"""Tool trace ring buffer and export helpers."""

import json

import pytest
import yumi.core.platform.tools.trace as trace_mod
from yumi.core.platform.tools.trace import (
    clear_memory_buffer,
    export_traces_json_lines,
    list_traces,
    record_tool_trace,
)


@pytest.fixture(autouse=True)
def isolated_trace_store(monkeypatch, tmp_path):
    clear_memory_buffer()
    monkeypatch.setattr(trace_mod, "_disk_bootstrapped", False)
    monkeypatch.setattr(trace_mod, "_trace_file", lambda: tmp_path / "tool_traces.jsonl")
    yield
    clear_memory_buffer()


def test_record_list_filter_and_export_roundtrip():
    record_tool_trace(
        session_id="s-a",
        tool_name="t1",
        kind="server",
        edge_name=None,
        display_name="T1",
        arguments={"x": 1},
        status="ok",
        duration_ms=12,
        result_preview="done",
    )
    record_tool_trace(
        session_id="s-b",
        tool_name="t2",
        kind="server",
        edge_name=None,
        display_name="T2",
        arguments={},
        status="error",
        duration_ms=3,
        result_preview=None,
    )
    all_rows = list_traces(session_id=None, limit=50)
    assert len(all_rows) == 2
    assert all_rows[0]["session_id"] == "s-b"

    only_b = list_traces(session_id="s-b", limit=50)
    assert len(only_b) == 1
    assert only_b[0]["tool_name"] == "t2"

    nd = export_traces_json_lines(session_id=None)
    lines = [json.loads(line) for line in nd.strip().splitlines()]
    assert len(lines) == 2
    assert lines[0]["session_id"] == "s-a"
    assert lines[1]["session_id"] == "s-b"


def test_record_redacts_sensitive_arguments_and_json_result_preview():
    record_tool_trace(
        session_id="s-a",
        tool_name="send_request",
        kind="server",
        edge_name=None,
        display_name="send_request",
        arguments={
            "url": "https://example.test",
            "api_key": "sk-secret",
            "nested": {"access_token": "tok-secret", "safe": "ok"},
        },
        status="ok",
        duration_ms=1,
        result_preview='{"password":"pw-secret","message":"done"}',
    )

    row = list_traces(limit=1)[0]
    assert row["arguments"]["url"] == "https://example.test"
    assert row["arguments"]["api_key"] == "[redacted]"
    assert row["arguments"]["nested"]["access_token"] == "[redacted]"
    assert row["arguments"]["nested"]["safe"] == "ok"
    assert "pw-secret" not in row["result_preview"]
    assert "[redacted]" in row["result_preview"]
