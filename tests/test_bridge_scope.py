"""BridgeScope plugin port: single-user default + plugin override.

The override test is the important one — it proves a higher layer can replace
how a messaging-bridge user maps to a session/connection (the single insertion
point needed for per-user routing), without touching bridge code.
"""

from yumi.core.platform.plugins import BridgeScope, get_bridge_scope, register_plugin


def test_single_user_default_session_ids():
    b = get_bridge_scope()
    assert isinstance(b, BridgeScope)
    assert b.session_id("telegram", "123") == "tg_123"
    assert b.session_id("discord", "456") == "dc_456"
    assert b.session_id("line", "789") == "line_789"


def test_single_user_link_is_a_noop_message():
    msg = get_bridge_scope().link("telegram", "123", "ANYCODE")
    assert "single-user" in msg.lower()


def test_plugin_can_override_bridge_scope():
    class _FakeScope:
        def session_id(self, channel: str, channel_user_id: str) -> str:
            return f"u42:{channel}:{channel_user_id}"

        def connection(self, channel: str, channel_user_id: str):
            return f"conn-for-{channel_user_id}"

        def link(self, channel: str, channel_user_id: str, code: str) -> str:
            return f"linked {channel_user_id} via {code}"

    original = get_bridge_scope()
    try:
        register_plugin(bridge_scope=_FakeScope())
        b = get_bridge_scope()
        assert b.session_id("telegram", "9") == "u42:telegram:9"
        assert b.connection("discord", "9") == "conn-for-9"
        assert b.link("telegram", "9", "abc") == "linked 9 via abc"
    finally:
        register_plugin(bridge_scope=original)
