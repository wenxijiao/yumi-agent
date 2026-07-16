"""Discord bridge: helpers, allowed-user gating, and the chat handler rendering.

discord.py and httpx are never exercised over the network here — the handler
talks to a fake channel object, and the one HTTP-shaped call (``_post_tool_confirm``)
is monkeypatched.
"""

import asyncio

import yumi.discord.bot as bot
from yumi.core.platform.http.events import ErrorEvent, TextEvent, ToolConfirmationEvent
from yumi.core.platform.plugins.single_user import SingleUserBridgeScope
from yumi.core.platform.security.connection import ConnectionConfig


class _FakeChannel:
    """Records everything sent to the Discord channel."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, content=None, *, view=None):
        self.sent.append({"content": content, "view": view})
        return None


def _connection() -> ConnectionConfig:
    return ConnectionConfig(mode="direct", scope="chat", base_url="http://127.0.0.1:8000")


# ── pure helpers ────────────────────────────────────────────────────────────


def test_format_timer_list_for_discord_empty():
    assert bot._format_timer_list_for_discord([]) == "No active timers or scheduled tasks."


def test_format_timer_list_for_discord_contains_cancel_hint():
    text = bot._format_timer_list_for_discord(
        [
            {
                "id": "abc123",
                "type": "scheduled",
                "recurring": True,
                "next_fire_at": "2026-05-14T09:00:00",
                "description": "daily check",
            }
        ]
    )
    assert "abc123" in text
    assert "daily check" in text
    assert "!cancel_timer <id>" in text


def test_truncate_for_discord_respects_2000_limit():
    out = bot._truncate_for_discord("x" * 5000)
    assert len(out) <= 2000
    assert out.endswith("…")


def test_session_id_for_user():
    assert bot._session_id_for_user(42) == "dc_42"


# ── allowed-user gating ─────────────────────────────────────────────────────


def test_authorized_no_allowlist_requires_explicit_allow_all(monkeypatch):
    monkeypatch.setattr(bot, "get_discord_allowed_user_ids", lambda: [])
    monkeypatch.setattr("yumi.core.platform.plugins.get_bridge_scope", lambda: SingleUserBridgeScope())
    monkeypatch.delenv("YUMI_BRIDGE_ALLOW_ALL", raising=False)
    assert bot._authorized(123) is False
    monkeypatch.setenv("YUMI_BRIDGE_ALLOW_ALL", "true")
    assert bot._authorized(123) is True


def test_authorized_no_allowlist_allows_enterprise_bridge_scope(monkeypatch):
    class _EnterpriseBridgeScope:
        pass

    monkeypatch.setattr(bot, "get_discord_allowed_user_ids", lambda: [])
    monkeypatch.setattr("yumi.core.platform.plugins.get_bridge_scope", lambda: _EnterpriseBridgeScope())
    assert bot._authorized(123) is True


def test_authorized_with_allowlist(monkeypatch):
    monkeypatch.setattr(bot, "get_discord_allowed_user_ids", lambda: [111])
    assert bot._authorized(111) is True
    assert bot._authorized(222) is False


def test_authorized_none_user_rejected(monkeypatch):
    monkeypatch.setattr(bot, "get_discord_allowed_user_ids", lambda: [])
    assert bot._authorized(None) is False


# ── handler: a text turn ────────────────────────────────────────────────────


def test_handler_text_turn_accumulates_and_renders():
    async def _run():
        channel = _FakeChannel()
        handler = bot._DiscordChatHandler(channel=channel, connection=_connection())
        await handler.on_text(TextEvent(content="Hello "))
        await handler.on_text(TextEvent(content="world"))
        assert handler.final_text() == "Hello world"

    asyncio.run(_run())


def test_handler_error_sends_message():
    async def _run():
        channel = _FakeChannel()
        handler = bot._DiscordChatHandler(channel=channel, connection=_connection())
        await handler.on_error(ErrorEvent(content="boom"))
        assert len(channel.sent) == 1
        assert "boom" in channel.sent[0]["content"]

    asyncio.run(_run())


# ── handler: tool-confirmation approve / deny ───────────────────────────────


def _confirmation_event() -> ToolConfirmationEvent:
    return ToolConfirmationEvent(
        call_id="call-1",
        tool_name="delete_file",
        full_tool_name="edge_fs__delete_file",
        arguments={"path": "/tmp/x"},
    )


def _drive_confirmation(monkeypatch, click: str) -> str:
    """Run one confirmation turn, auto-clicking ``click`` once the prompt is posted.

    Returns the decision string the handler posted to ``/tools/confirm``.
    """
    posted: dict[str, str] = {}

    async def _fake_post(connection, call_id, decision):
        posted["call_id"] = call_id
        posted["decision"] = decision
        return True, ""

    monkeypatch.setattr(bot, "_post_tool_confirm", _fake_post)

    class _ClickingChannel(_FakeChannel):
        async def send(self, content=None, *, view=None):
            await super().send(content=content, view=view)
            if view is not None:
                # Resolve the View's future as if a button was clicked.
                view._future_for_test.set_result(click)  # type: ignore[attr-defined]

    # Patch the view builder to stash the future so the fake channel can click.
    real_build = bot._build_confirmation_view

    def _build(future, timeout):
        view = real_build(future, timeout)
        view._future_for_test = future  # type: ignore[attr-defined]
        return view

    monkeypatch.setattr(bot, "_build_confirmation_view", _build)

    async def _run():
        channel = _ClickingChannel()
        handler = bot._DiscordChatHandler(channel=channel, connection=_connection())
        await handler.on_tool_confirmation(_confirmation_event())

    asyncio.run(_run())
    assert posted["call_id"] == "call-1"
    return posted["decision"]


def test_tool_confirmation_allow(monkeypatch):
    assert _drive_confirmation(monkeypatch, "allow") == "allow"


def test_tool_confirmation_deny(monkeypatch):
    assert _drive_confirmation(monkeypatch, "deny") == "deny"


def test_tool_confirmation_always_maps_to_always_allow(monkeypatch):
    assert _drive_confirmation(monkeypatch, "always") == "always_allow"


# ── /link accepted as plain text (documented form; native prefix is "!") ────


def test_slash_link_reply_redeems_code(monkeypatch):
    class _Scope:
        def link(self, channel, channel_user_id, code):
            assert channel == "discord"
            assert channel_user_id == "123"
            assert code == "yumi_abc"
            return "linked!"

    monkeypatch.setattr("yumi.core.platform.plugins.get_bridge_scope", lambda: _Scope())
    assert bot._slash_link_reply("/link yumi_abc", 123) == "linked!"
    assert bot._slash_link_reply("/LINK yumi_abc", 123) == "linked!"


def test_slash_link_reply_ignores_other_messages(monkeypatch):
    monkeypatch.setattr(
        "yumi.core.platform.plugins.get_bridge_scope",
        lambda: (_ for _ in ()).throw(AssertionError("must not resolve scope")),
    )
    assert bot._slash_link_reply("hello there", 123) is None
    assert bot._slash_link_reply("link me up", 123) is None
    assert bot._slash_link_reply("/link yumi_abc", None) is None
