"""Discord outbound (timer/proactive push) helpers — no real network."""

import asyncio

import yumi.discord.notify as notify


def test_parse_discord_user_id_valid():
    assert notify.parse_discord_user_id("dc_4815162342") == 4815162342


def test_parse_discord_user_id_rejects_other_channels():
    assert notify.parse_discord_user_id("tg_123") is None
    assert notify.parse_discord_user_id("line_abc") is None
    assert notify.parse_discord_user_id("chat_1") is None


def test_chunk_message_splits_over_2000():
    chunks = notify._chunk_message("y" * 4500)
    assert len(chunks) == 3
    assert all(len(c) <= 2000 for c in chunks)
    assert "".join(chunks) == "y" * 4500


def test_events_to_plain_text_only_text():
    events = [
        {"type": "text", "content": "hi "},
        {"type": "tool_status", "content": "running"},
        {"type": "text", "content": "there"},
    ]
    assert notify._events_to_plain_text(events) == "hi there"


def test_send_text_to_discord_noop_without_token(monkeypatch):
    monkeypatch.setattr(notify, "get_discord_bot_token", lambda: None)

    async def _run():
        return await notify.send_text_to_discord("dc_1", "hello")

    assert asyncio.run(_run()) is False


def test_send_timer_result_skips_non_discord_session(monkeypatch):
    # Should return before touching the token at all.
    monkeypatch.setattr(notify, "get_discord_bot_token", lambda: "should-not-be-read")

    async def _run():
        await notify.send_timer_result_to_discord("tg_5", "desc", [{"type": "text", "content": "x"}])

    asyncio.run(_run())
