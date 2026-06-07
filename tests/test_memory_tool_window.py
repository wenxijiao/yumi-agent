"""Session row trimming for tool replay (sliding window must not split tool turns)."""

import json

from kumi.core.features.memory.constants import KUMI_V1_TOOL_CALLS, KUMI_V1_TOOL_RESULT
from kumi.core.features.memory.memory import (
    _assistant_tool_call_count_from_stored_raw,
    _dedupe_consecutive_user_rows,
    _trim_leading_orphan_assistant_tool_calls,
    _trim_leading_orphan_tool_rows,
    _trim_trailing_incomplete_tool_rows,
)


def _tc_payload(n: int) -> str:
    calls = [{"id": str(i), "type": "function", "function": {"name": f"t{i}", "arguments": "{}"}} for i in range(n)]
    return KUMI_V1_TOOL_CALLS + json.dumps({"content": "", "tool_calls": calls})


def test_trailing_incomplete_drops_suffix():
    rows = [
        {"role": "user", "content": "hi", "timestamp": "1"},
        {"role": "assistant", "content": _tc_payload(2), "timestamp": "2"},
        {
            "role": "tool",
            "content": KUMI_V1_TOOL_RESULT + json.dumps({"name": "t0", "content": "x"}),
            "timestamp": "3",
        },
    ]
    out = _trim_trailing_incomplete_tool_rows(rows)
    assert len(out) == 1 and out[0]["role"] == "user"


def test_complete_tool_block_kept():
    t1 = KUMI_V1_TOOL_CALLS + json.dumps(
        {
            "content": "",
            "tool_calls": [{"id": "1", "type": "function", "function": {"name": "a", "arguments": "{}"}}],
        }
    )
    rows = [
        {"role": "user", "content": "hi", "timestamp": "1"},
        {"role": "assistant", "content": t1, "timestamp": "2"},
        {"role": "tool", "content": KUMI_V1_TOOL_RESULT + json.dumps({"name": "a", "content": "x"}), "timestamp": "3"},
    ]
    out = _trim_trailing_incomplete_tool_rows(rows)
    assert len(out) == 3


def test_leading_orphan_tools_removed():
    rows = [
        {"role": "tool", "content": "x"},
        {"role": "user", "content": "hi"},
    ]
    out = _trim_leading_orphan_tool_rows(rows)
    assert [r["role"] for r in out] == ["user"]


def test_assistant_tool_call_count_parsed():
    assert _assistant_tool_call_count_from_stored_raw("plain") is None
    raw = _tc_payload(3)
    assert _assistant_tool_call_count_from_stored_raw(raw) == 3


def test_leading_orphan_assistant_tool_call_removed():
    rows = [
        {"role": "assistant", "content": _tc_payload(1), "timestamp": "1"},
        {
            "role": "tool",
            "content": KUMI_V1_TOOL_RESULT + json.dumps({"name": "t0", "content": "ok"}),
            "timestamp": "2",
        },
        {"role": "user", "content": "morning", "timestamp": "3"},
    ]
    out = _trim_leading_orphan_assistant_tool_calls(rows)
    assert [r["role"] for r in out] == ["user"]


def test_leading_orphan_assistant_tool_call_keeps_normal_assistant_text():
    rows = [
        {"role": "assistant", "content": "hello", "timestamp": "1"},
        {"role": "user", "content": "next", "timestamp": "2"},
    ]
    out = _trim_leading_orphan_assistant_tool_calls(rows)
    assert [r["role"] for r in out] == ["assistant", "user"]


def test_leading_orphan_assistant_tool_call_strips_multiple_blocks():
    rows = [
        {"role": "assistant", "content": _tc_payload(1), "timestamp": "1"},
        {
            "role": "tool",
            "content": KUMI_V1_TOOL_RESULT + json.dumps({"name": "t0", "content": "ok"}),
            "timestamp": "2",
        },
        {"role": "assistant", "content": _tc_payload(2), "timestamp": "3"},
        {
            "role": "tool",
            "content": KUMI_V1_TOOL_RESULT + json.dumps({"name": "t0", "content": "ok"}),
            "timestamp": "4",
        },
        {
            "role": "tool",
            "content": KUMI_V1_TOOL_RESULT + json.dumps({"name": "t1", "content": "ok"}),
            "timestamp": "5",
        },
        {"role": "user", "content": "later", "timestamp": "6"},
    ]
    out = _trim_leading_orphan_assistant_tool_calls(rows)
    assert [r["role"] for r in out] == ["user"]


def test_dedupe_consecutive_user_rows_keeps_latest():
    rows = [
        {"role": "user", "content": "晚安", "timestamp": "1"},
        {"role": "user", "content": "晚安", "timestamp": "2"},
        {"role": "user", "content": "晚安", "timestamp": "3"},
    ]
    out = _dedupe_consecutive_user_rows(rows)
    assert len(out) == 1
    assert out[0]["timestamp"] == "3"


def test_dedupe_consecutive_user_rows_preserves_other_runs():
    rows = [
        {"role": "user", "content": "hi", "timestamp": "1"},
        {"role": "user", "content": "hi", "timestamp": "2"},
        {"role": "assistant", "content": "hello", "timestamp": "3"},
        {"role": "user", "content": "hi", "timestamp": "4"},
    ]
    out = _dedupe_consecutive_user_rows(rows)
    assert [r.get("timestamp") for r in out] == ["2", "3", "4"]


def test_dedupe_consecutive_user_rows_ignores_different_text():
    rows = [
        {"role": "user", "content": "hi", "timestamp": "1"},
        {"role": "user", "content": "hello", "timestamp": "2"},
    ]
    out = _dedupe_consecutive_user_rows(rows)
    assert len(out) == 2


def test_dedupe_consecutive_user_rows_skips_empty_content():
    rows = [
        {"role": "user", "content": "", "timestamp": "1"},
        {"role": "user", "content": "", "timestamp": "2"},
    ]
    out = _dedupe_consecutive_user_rows(rows)
    assert len(out) == 2
