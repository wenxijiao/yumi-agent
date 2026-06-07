"""Gemini rejects edge tool names with spaces or other disallowed characters."""

from kumi.core.api.state import edge_tool_key_prefix, gemini_safe_edge_segment


def test_gemini_safe_edge_segment_strips_spaces_and_unicode():
    assert gemini_safe_edge_segment("test-device") == "test-device"
    assert gemini_safe_edge_segment("My Device") == "My_Device"
    assert gemini_safe_edge_segment("  ") == "edge"


def test_edge_tool_key_prefix_matches_gemini_rules():
    p = edge_tool_key_prefix("My Device")
    assert p.startswith("edge_")
    assert p.endswith("__")
    assert " " not in p
    full = f"{p}memori_ping"
    allowed = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.:-")
    assert all(c in allowed for c in full)
