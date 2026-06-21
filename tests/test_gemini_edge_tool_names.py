"""Gemini rejects edge tool names with spaces or other disallowed characters."""

from yumi.core.platform.runtime.accessors import edge_tool_key_prefix, gemini_safe_edge_segment


def test_gemini_safe_edge_segment_strips_spaces_and_unicode():
    assert gemini_safe_edge_segment("test-device") == "test-device"
    assert gemini_safe_edge_segment("My Device") == "My_Device"
    assert gemini_safe_edge_segment("  ") == "edge"


def test_edge_tool_key_prefix_matches_gemini_rules():
    p = edge_tool_key_prefix("My Device")
    assert p.startswith("edge_")
    assert p.endswith("__")
    assert " " not in p
    full = f"{p}device_ping"
    # Provider-safe charset (OpenAI/Anthropic strictest): no '.' or ':'.
    allowed = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
    assert all(c in allowed for c in full)


def test_segment_normalizes_provider_illegal_chars_and_caps_length():
    # '.' and ':' are valid for Gemini but rejected by OpenAI/Anthropic, so they
    # are normalized to '_' (else the server would silently drop the tool).
    assert gemini_safe_edge_segment("my.device") == "my_device"
    assert gemini_safe_edge_segment("host:8000") == "host_8000"
    out = gemini_safe_edge_segment("a.b:c d/e")
    assert all(c.isalnum() or c in "_-" for c in out)
    # capped well under the 64-char provider limit (leaves room for prefix + tool)
    assert len(gemini_safe_edge_segment("x" * 200)) <= 32
