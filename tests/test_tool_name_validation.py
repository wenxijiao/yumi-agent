"""Provider-safe tool-name validation (core helper + Python SDK register)."""

import pytest
from yumi.core.platform.tools.validation import is_valid_tool_name
from yumi.sdk import YumiAgent


def test_is_valid_tool_name_accepts_and_rejects():
    assert is_valid_tool_name("get_weather")
    assert is_valid_tool_name("tool-1")
    assert is_valid_tool_name("A" * 64)
    # rejects
    assert not is_valid_tool_name("has space")
    assert not is_valid_tool_name("emoji\U0001f600")
    assert not is_valid_tool_name("dot.name")
    assert not is_valid_tool_name("paren()")
    assert not is_valid_tool_name("")
    assert not is_valid_tool_name("A" * 65)
    assert not is_valid_tool_name(None)


def test_sdk_register_rejects_invalid_names():
    agent = YumiAgent(edge_name="test-edge")
    with pytest.raises(ValueError):
        agent.register(lambda: 1, "desc", name="bad name")
    with pytest.raises(ValueError):
        agent.register(lambda: 1, "desc", name="emoji\U0001f600")
    # a valid name still registers cleanly
    agent.register(lambda: 1, "desc", name="good_name-1")
