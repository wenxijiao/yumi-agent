from __future__ import annotations

from yumi.core.platform.providers.claude_provider import _build_claude_messages, _max_tokens_for_model


def test_claude_tool_results_pair_with_prior_tool_use_ids_by_name():
    _, messages = _build_claude_messages(
        [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "call-weather", "function": {"name": "weather", "arguments": "{}"}},
                    {"id": "call-clock", "function": {"name": "clock", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "name": "clock", "content": "12:00"},
            {"role": "tool", "name": "weather", "content": "clear"},
        ]
    )

    assert messages[1]["content"][0]["tool_use_id"] == "call-clock"
    assert messages[2]["content"][0]["tool_use_id"] == "call-weather"


def test_claude_tool_result_explicit_id_wins_over_name():
    _, messages = _build_claude_messages(
        [
            {
                "role": "assistant",
                "tool_calls": [
                    {"id": "call-a", "function": {"name": "same", "arguments": "{}"}},
                    {"id": "call-b", "function": {"name": "same", "arguments": "{}"}},
                ],
            },
            {"role": "tool", "tool_call_id": "call-b", "name": "same", "content": "b"},
            {"role": "tool", "name": "same", "content": "a"},
        ]
    )

    assert messages[1]["content"][0]["tool_use_id"] == "call-b"
    assert messages[2]["content"][0]["tool_use_id"] == "call-a"


def test_claude_opus_3_max_tokens_is_clamped_to_supported_limit():
    assert _max_tokens_for_model("claude-3-opus-20240229") == 4096
    assert _max_tokens_for_model("claude-3-5-sonnet-20241022") == 8192
