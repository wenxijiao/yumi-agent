"""Per-chat voice-reply toggle + the Telegram audio-send helper."""

import asyncio
import types

from yumi.core.features.tts import reply_mode


def test_toggle_is_per_channel_and_chat():
    reply_mode.set_voice_reply("telegram", 1, True)
    assert reply_mode.is_voice_reply("telegram", 1)
    assert not reply_mode.is_voice_reply("telegram", 2)  # other chat unaffected
    assert not reply_mode.is_voice_reply("discord", 1)  # other channel unaffected
    reply_mode.set_voice_reply("telegram", 1, False)
    assert not reply_mode.is_voice_reply("telegram", 1)


def test_telegram_send_voice_reply_uploads_audio(monkeypatch):
    from yumi.telegram import bot

    async def fake_synth(text, *, config=None):
        return types.SimpleNamespace(data=b"WAVDATA", format="wav")

    monkeypatch.setattr("yumi.core.features.tts.playback.synthesize_with_fallback", fake_synth)
    sent = {}

    class FakeBot:
        async def send_audio(self, chat_id, audio, caption=None):
            sent.update(chat_id=chat_id, name=audio.name, data=audio.read(), caption=caption)

    context = types.SimpleNamespace(bot=FakeBot())
    ok = asyncio.run(bot._send_voice_reply(context, 42, "hello there"))

    assert ok is True
    assert sent["chat_id"] == 42
    assert sent["data"] == b"WAVDATA"
    assert sent["name"].endswith(".wav")
    assert sent["caption"] == "hello there"


def test_telegram_send_voice_reply_returns_false_on_failure(monkeypatch):
    from yumi.telegram import bot

    async def boom(text, *, config=None):
        raise RuntimeError("tts unavailable")

    monkeypatch.setattr("yumi.core.features.tts.playback.synthesize_with_fallback", boom)
    context = types.SimpleNamespace(bot=types.SimpleNamespace())
    ok = asyncio.run(bot._send_voice_reply(context, 7, "hi"))
    assert ok is False
