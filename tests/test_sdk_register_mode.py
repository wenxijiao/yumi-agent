"""SDK register() exposure-mode mapping: mode -> existing wire flags."""

import pytest
from yumi.sdk import YumiAgent


def _agent() -> YumiAgent:
    return YumiAgent(edge_name="test-edge")


def test_mode_autorun_maps_to_context_fields():
    a = _agent()
    a.register(
        lambda: "x",
        "desc",
        mode="autorun",
        context_args={"city": "AKL"},
        context_label="User context",
        name="ctx",
    )
    e = a._tools["ctx"]
    assert e["proactive_context"] is True
    assert e["proactive_context_args"] == {"city": "AKL"}
    assert e["proactive_context_description"] == "User context"
    assert e["always_include"] is False


def test_mode_pinned_maps_to_always_include():
    a = _agent()
    a.register(lambda: "y", "desc", mode="pinned", name="alw")
    e = a._tools["alw"]
    assert e["always_include"] is True
    assert e["proactive_context"] is False


def test_mode_dynamic_is_the_default():
    a = _agent()
    a.register(lambda: "z", "desc", name="ret")
    e = a._tools["ret"]
    assert e["always_include"] is False
    assert e["proactive_context"] is False


def test_invalid_mode_raises():
    a = _agent()
    with pytest.raises(ValueError):
        a.register(lambda: 1, "desc", mode="bogus", name="bad")


def test_terminal_policy_roundtrips_registration_but_is_not_a_model_argument(monkeypatch):
    from yumi.core.features.edge import api
    from yumi.core.platform.runtime.tool_catalog import model_visible_tool_schema
    from yumi.sdk.python.agent_client import _wire_tool_schema

    monkeypatch.setattr(api, "EDGE_TOOLS_REGISTRY", {})
    monkeypatch.setattr("yumi.core.platform.tools.indexing.schedule_tool_index", lambda *a: None)
    a = _agent()
    a.register(lambda: {"ok": True}, "Play", name="play", reply_on_success=False)
    a.register(lambda: "status", "Status", name="status")
    wire = _wire_tool_schema(a._tools["play"])
    assert wire["reply_on_success"] is False
    assert "reply_on_success" not in wire["function"]["parameters"]["properties"]
    assert "reply_on_success" not in _wire_tool_schema(a._tools["status"])
    api._mount_edge_tools("fixture", "edge_fixture__", [wire])
    entry = api.EDGE_TOOLS_REGISTRY["fixture"]["edge_fixture__play"]
    assert entry["reply_on_success"] is False
    assert "reply_on_success" not in entry["schema"]
    assert "reply_on_success" not in model_visible_tool_schema(wire)
    with pytest.raises(ValueError, match="boolean"):
        a.register(lambda: None, "Bad", name="bad", reply_on_success="false")


def test_sdk_dictionary_result_is_valid_json_for_success_contract():
    import asyncio
    import json

    a = _agent()
    a.register(lambda: {"ok": True, "song": "夜に駆ける"}, "Play", name="play", reply_on_success=False)
    messages = []

    class Socket:
        async def send(self, raw):
            messages.append(json.loads(raw))

    asyncio.run(a._handle_tool_call(Socket(), {"name": "play", "call_id": "one", "arguments": {}}))
    assert json.loads(messages[0]["result"]) == {"ok": True, "song": "夜に駆ける"}


def test_deprecated_flags_still_honored():
    a = _agent()
    a.register(lambda: 1, "desc", always_include=True, name="old")
    assert a._tools["old"]["always_include"] is True


def test_confirmation_template_is_optional_wire_metadata():
    from yumi.sdk.python.agent_client import _wire_tool_schema

    agent = _agent()

    def weather(city: str, day: str = "后天"):
        return city + day

    agent.register(weather, "Weather", name="weather", confirmation_template={"zh": "查询「{city}」「{day}」的天气"})
    wire = _wire_tool_schema(agent._tools["weather"])
    from yumi.core.platform.tools.presentation import render_action_summary

    assert (
        render_action_summary(
            wire["confirmation_template"], {"city": "奥克兰"}, wire["function"]["parameters"], locale="zh"
        )
        == "查询「奥克兰」「后天」的天气"
    )
    assert "confirmation_template" not in wire["function"]


def test_pairing_token_storage_is_private_and_scoped(tmp_path, monkeypatch):
    import os

    agent = _agent()
    agent._connection_code = "code-A"
    monkeypatch.setattr("os.path.expanduser", lambda path: str(tmp_path) if path == "~" else path)
    url = "wss://test.example/ws/edge"
    agent._save_pairing_token(url, "test-credential")
    assert agent._load_pairing_token(url) == "test-credential"
    assert os.stat(agent._pairing_file(url)).st_mode & 0o777 == 0o600
    assert agent._load_pairing_token("wss://other.example/ws/edge") is None
    agent._connection_code = "code-B"
    assert agent._load_pairing_token(url) is None
    agent._connection_code = "code-A"
    agent._edge_name = "other-device"
    assert agent._load_pairing_token(url) is None
