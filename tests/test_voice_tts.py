"""Voice mode speaks replies aloud (with a system-voice fallback)."""

import asyncio
import types

from yumi.voice import dispatch


class _FakeProvider:
    def __init__(self, tag: bytes):
        self._tag = tag

    async def synthesize(self, text: str):
        return types.SimpleNamespace(data=self._tag, format="wav")


def test_speaks_with_configured_provider(monkeypatch):
    played = {}
    monkeypatch.setattr("yumi.core.features.config.load_model_config", lambda: object())
    monkeypatch.setattr(
        "yumi.core.features.tts.factory.create_tts_provider",
        lambda cfg: _FakeProvider(b"CONFIGURED"),
    )
    monkeypatch.setattr("yumi.core.features.tts.playback.play_audio", lambda a: played.update(d=a.data))

    asyncio.run(dispatch._speak_voice_reply("hello"))
    assert played["d"] == b"CONFIGURED"


def test_falls_back_to_system_voice_when_tts_disabled(monkeypatch):
    from yumi.core.features.tts.base import TtsNotConfiguredError

    def _disabled(cfg):
        raise TtsNotConfiguredError("off")

    played = {}
    monkeypatch.setattr("yumi.core.features.config.load_model_config", lambda: object())
    monkeypatch.setattr("yumi.core.features.tts.factory.create_tts_provider", _disabled)
    monkeypatch.setattr(
        "yumi.core.features.tts.system_provider.SystemTtsProvider",
        lambda: _FakeProvider(b"SYSTEM"),
    )
    monkeypatch.setattr("yumi.core.features.tts.playback.play_audio", lambda a: played.update(d=a.data))

    asyncio.run(dispatch._speak_voice_reply("hello"))
    assert played["d"] == b"SYSTEM"


def test_playback_failure_is_swallowed(monkeypatch):
    def _boom(a):
        raise RuntimeError("no audio device")

    monkeypatch.setattr("yumi.core.features.config.load_model_config", lambda: object())
    monkeypatch.setattr(
        "yumi.core.features.tts.factory.create_tts_provider",
        lambda cfg: _FakeProvider(b"X"),
    )
    monkeypatch.setattr("yumi.core.features.tts.playback.play_audio", _boom)

    # must not raise
    asyncio.run(dispatch._speak_voice_reply("hello"))
