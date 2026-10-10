from yumi.core.platform.runtime.assistant_context import message_media
from yumi.core.platform.tools.routing import ToolCatalog
from yumi.core.platform.tools.tool import TOOL_REGISTRY, register_tool
from yumi.tools.voice_tools import end_voice_conversation


def test_standby_tool_is_hidden_and_inert_outside_capable_voice_sessions(monkeypatch):
    name = "end_voice_conversation"
    monkeypatch.setitem(TOOL_REGISTRY, name, {})
    register_tool(end_voice_conversation, "End voice", reply_on_success=False)
    for enabled in [False, True]:
        token = message_media.set({"voice_session_controls": enabled})
        try:
            names = {e.name for e in ToolCatalog(disabled_tools=set(), edge_registry={}).core_tools()}
            assert (name in names) is enabled
            assert end_voice_conversation()["ok"] is enabled
        finally:
            message_media.reset(token)
