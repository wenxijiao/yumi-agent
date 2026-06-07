"""Unit tests for yumi.core.features.prompts.http_bridge helpers."""

from yumi.core.features.prompts.defaults import UPLOAD_FILE_INSTRUCTION, build_tool_use_instruction
from yumi.core.features.prompts.http_bridge import format_effective_prompt_reply, truncate_for_bot_display


def test_truncate_for_bot_display() -> None:
    assert truncate_for_bot_display("ab", max_chars=10) == "ab"
    long = "x" * 100
    out = truncate_for_bot_display(long, max_chars=20)
    assert len(out) == 20
    assert out.endswith("…")


def test_format_effective_prompt_reply() -> None:
    text = format_effective_prompt_reply(effective="hi", source_label="Global default")
    assert "Global default" in text
    assert "hi" in text


def test_tool_use_instruction_lists_only_current_tools() -> None:
    text = build_tool_use_instruction(
        [
            {"type": "function", "function": {"name": "read_file", "description": "Read files"}},
            {"type": "function", "function": {"name": "get_weather", "description": "Get weather"}},
        ]
    )

    assert "Available callable tools in this turn: `read_file`, `get_weather`." in text
    assert "Only claim or call tools that are listed above" in text
    assert "lights" not in text
    assert "temperature" not in text
    assert "gates" not in text
    assert "Smart Home" not in text


def test_tool_use_instruction_does_not_force_unavailable_file_tool() -> None:
    text = build_tool_use_instruction([{"type": "function", "function": {"name": "web_search"}}])

    assert "read_file" not in text
    assert "web_search" in text


def test_upload_instruction_is_conditional_on_read_file_availability() -> None:
    assert "If `read_file` is available" in UPLOAD_FILE_INSTRUCTION
    assert "runtime provides `read_file`" not in UPLOAD_FILE_INSTRUCTION
