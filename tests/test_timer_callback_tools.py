"""Timer follow-up turns must not offer ``set_timer`` / ``schedule_task`` (loops chain delays)."""

from kumi.core.features.chat.service import _exclude_delay_scheduling_tools


def test_excludes_delay_tools_from_openai_schemas():
    tools = [
        {"type": "function", "function": {"name": "set_timer"}},
        {"type": "function", "function": {"name": "schedule_task"}},
        {"type": "function", "function": {"name": "get_weather"}},
    ]
    out = _exclude_delay_scheduling_tools(tools)
    assert [t["function"]["name"] for t in (out or [])] == ["get_weather"]


def test_returns_none_when_only_delay_tools():
    tools = [{"type": "function", "function": {"name": "set_timer"}}]
    assert _exclude_delay_scheduling_tools(tools) is None


def test_empty_and_none_passthrough():
    assert _exclude_delay_scheduling_tools(None) is None
    assert _exclude_delay_scheduling_tools([]) == []
