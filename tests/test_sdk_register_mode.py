"""SDK register() exposure-mode mapping: mode -> existing wire flags."""

import pytest
from yumi.sdk import YumiAgent


def _agent() -> YumiAgent:
    return YumiAgent(edge_name="test-edge")


def test_mode_context_maps_to_proactive_fields():
    a = _agent()
    a.register(
        lambda: "x",
        "desc",
        mode="context",
        context_args={"city": "AKL"},
        context_label="User context",
        name="ctx",
    )
    e = a._tools["ctx"]
    assert e["proactive_context"] is True
    assert e["proactive_context_args"] == {"city": "AKL"}
    assert e["proactive_context_description"] == "User context"
    assert e["always_include"] is False


def test_mode_always_maps_to_always_include():
    a = _agent()
    a.register(lambda: "y", "desc", mode="always", name="alw")
    e = a._tools["alw"]
    assert e["always_include"] is True
    assert e["proactive_context"] is False


def test_mode_retrieval_is_the_default():
    a = _agent()
    a.register(lambda: "z", "desc", name="ret")
    e = a._tools["ret"]
    assert e["always_include"] is False
    assert e["proactive_context"] is False


def test_invalid_mode_raises():
    a = _agent()
    with pytest.raises(ValueError):
        a.register(lambda: 1, "desc", mode="bogus", name="bad")


def test_deprecated_flags_still_honored():
    a = _agent()
    a.register(lambda: 1, "desc", always_include=True, name="old")
    assert a._tools["old"]["always_include"] is True
