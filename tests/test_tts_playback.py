"""Local playback + the high-level speak() helper (no real audio device)."""

import subprocess

import pytest
from yumi.core.features.tts import playback
from yumi.core.features.tts.playback import PlaybackError, play_audio, resolve_player, speak
from yumi.core.features.tts.types import SpeechAudio


def test_resolve_player_none_when_no_command(monkeypatch):
    monkeypatch.setattr(playback.shutil, "which", lambda c: None)
    assert resolve_player() is None


def test_play_audio_without_player_raises(monkeypatch):
    monkeypatch.setattr(playback.sys, "platform", "darwin")  # exercise the POSIX path on any host
    monkeypatch.setattr(playback, "resolve_player", lambda: None)
    with pytest.raises(PlaybackError):
        play_audio(SpeechAudio(data=b"x", format="wav"))


def test_play_audio_on_windows_uses_winsound(monkeypatch):
    monkeypatch.setattr(playback.sys, "platform", "win32")
    seen = {}

    def fake_win(path):
        with open(path, "rb") as fh:
            seen["data"] = fh.read()

    monkeypatch.setattr(playback, "_play_windows", fake_win)
    play_audio(SpeechAudio(data=b"WINWAV", format="wav"))
    assert seen["data"] == b"WINWAV"


def test_play_audio_writes_temp_and_invokes_player(monkeypatch):
    monkeypatch.setattr(playback.sys, "platform", "darwin")  # exercise the POSIX path on any host
    monkeypatch.setattr(playback, "resolve_player", lambda: ["afplay"])
    seen = {}

    def fake_run(argv, check, capture_output):
        with open(argv[-1], "rb") as fh:
            seen["data"] = fh.read()
        seen["player"] = argv[0]
        return None

    monkeypatch.setattr(subprocess, "run", fake_run)
    play_audio(SpeechAudio(data=b"hello-bytes", format="wav"))
    assert seen == {"data": b"hello-bytes", "player": "afplay"}


def test_speak_synthesizes_then_plays(monkeypatch):
    played = {}

    class FakeProvider:
        async def synthesize(self, text, voice=None, language=None):
            return SpeechAudio(data=b"AUDIO", format="wav")

    monkeypatch.setattr(playback, "create_tts_provider", lambda config=None: FakeProvider())
    monkeypatch.setattr(playback, "play_audio", lambda audio: played.update(data=audio.data))
    speak("hello")
    assert played["data"] == b"AUDIO"


def test_synthesize_with_fallback_uses_configured_provider(monkeypatch):
    class FakeProvider:
        async def synthesize(self, text, voice=None, language=None):
            return SpeechAudio(data=b"CONFIGURED", format="wav")

    monkeypatch.setattr(playback, "create_tts_provider", lambda config=None: FakeProvider())
    import asyncio

    audio = asyncio.run(playback.synthesize_with_fallback("hi"))
    assert audio.data == b"CONFIGURED"


def test_synthesize_with_fallback_drops_to_system_voice(monkeypatch):
    from yumi.core.features.tts.base import TtsNotConfiguredError

    def _disabled(config=None):
        raise TtsNotConfiguredError("off")

    class FakeSystem:
        async def synthesize(self, text, voice=None, language=None):
            return SpeechAudio(data=b"SYSTEM", format="wav")

    monkeypatch.setattr(playback, "create_tts_provider", _disabled)
    monkeypatch.setattr("yumi.core.features.tts.system_provider.SystemTtsProvider", lambda: FakeSystem())
    import asyncio

    audio = asyncio.run(playback.synthesize_with_fallback("hi"))
    assert audio.data == b"SYSTEM"
