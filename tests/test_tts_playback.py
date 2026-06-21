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
    monkeypatch.setattr(playback, "resolve_player", lambda: None)
    with pytest.raises(PlaybackError):
        play_audio(SpeechAudio(data=b"x", format="wav"))


def test_play_audio_writes_temp_and_invokes_player(monkeypatch):
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
