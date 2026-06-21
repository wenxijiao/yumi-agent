"""Voice mode speaks replies aloud (synthesis + playback, both mocked)."""

import asyncio
import types

from yumi.voice import dispatch


def test_speaks_the_reply(monkeypatch):
    played = {}

    async def fake_synth(reply, *, config=None):
        return types.SimpleNamespace(data=b"AUDIO", format="wav")

    monkeypatch.setattr("yumi.core.features.config.load_model_config", lambda: object())
    monkeypatch.setattr("yumi.core.features.tts.playback.synthesize_with_fallback", fake_synth)
    monkeypatch.setattr("yumi.core.features.tts.playback.play_audio", lambda a: played.update(d=a.data))

    asyncio.run(dispatch._speak_voice_reply("hello"))
    assert played["d"] == b"AUDIO"


def test_playback_failure_is_swallowed(monkeypatch):
    async def fake_synth(reply, *, config=None):
        return types.SimpleNamespace(data=b"X", format="wav")

    def _boom(a):
        raise RuntimeError("no audio device")

    monkeypatch.setattr("yumi.core.features.config.load_model_config", lambda: object())
    monkeypatch.setattr("yumi.core.features.tts.playback.synthesize_with_fallback", fake_synth)
    monkeypatch.setattr("yumi.core.features.tts.playback.play_audio", _boom)

    asyncio.run(dispatch._speak_voice_reply("hello"))  # must not raise
