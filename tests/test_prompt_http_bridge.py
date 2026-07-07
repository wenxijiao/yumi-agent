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


def test_tool_use_instruction_does_not_enumerate_tool_names() -> None:
    """Tool names live in the request's ``tools`` schema list, not the system
    prompt: enumerating them there would duplicate tokens and change the
    prompt prefix every turn, breaking provider prompt caching."""
    text = build_tool_use_instruction(
        [
            {"type": "function", "function": {"name": "read_file", "description": "Read files"}},
            {"type": "function", "function": {"name": "get_weather", "description": "Get weather"}},
        ]
    )

    assert "Available callable tools in this turn" not in text
    assert "get_weather" not in text
    assert "Only claim or call tools that are exposed" in text
    # read_file guidance IS conditional on read_file being available.
    assert "read_file" in text


def test_tool_use_instruction_is_stable_across_tool_selections() -> None:
    """Two turns with different non-core tool selections must produce a
    byte-identical instruction, otherwise the system prompt churns per turn."""
    a = build_tool_use_instruction([{"type": "function", "function": {"name": "web_search"}}])
    b = build_tool_use_instruction(
        [
            {"type": "function", "function": {"name": "edge_home__toggle_light"}},
            {"type": "function", "function": {"name": "get_weather"}},
        ]
    )

    assert a == b
    assert "web_search" not in a


def test_tool_use_instruction_does_not_force_unavailable_file_tool() -> None:
    text = build_tool_use_instruction([{"type": "function", "function": {"name": "web_search"}}])

    assert "read_file" not in text


def test_upload_instruction_is_conditional_on_read_file_availability() -> None:
    assert "If `read_file` is available" in UPLOAD_FILE_INSTRUCTION
    assert "runtime provides `read_file`" not in UPLOAD_FILE_INSTRUCTION
