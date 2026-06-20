"""TTS foundation: factory selection + the zero-dependency system provider.

The OS speech command (`say`/`espeak`) may be absent in CI, so the provider's
command construction is unit-tested as a pure function and the subprocess call
is mocked — no real audio is generated here.
"""

import asyncio
import subprocess

import pytest
from yumi.core.features.config.model import ModelConfig
from yumi.core.features.tts import create_tts_provider
from yumi.core.features.tts.base import TtsError, TtsNotConfiguredError
from yumi.core.features.tts.system_provider import SystemTtsProvider
from yumi.core.features.tts.types import SpeechAudio


def test_factory_disabled_by_default():
    with pytest.raises(TtsNotConfiguredError):
        create_tts_provider(ModelConfig())


def test_factory_system_provider():
    provider = create_tts_provider(ModelConfig(tts_provider="system", tts_voice="Serena"))
    assert isinstance(provider, SystemTtsProvider)


def test_factory_unknown_provider_raises():
    with pytest.raises(TtsError):
        create_tts_provider(ModelConfig(tts_provider="totally-made-up"))


def test_build_argv_macos_say_includes_voice():
    argv = SystemTtsProvider._build_argv("say", "hello world", "Serena", "/tmp/o.wav")
    assert argv[0] == "say"
    assert "-o" in argv and "/tmp/o.wav" in argv
    assert argv[argv.index("-v") + 1] == "Serena"
    assert argv[-1] == "hello world"  # text is the trailing positional


def test_build_argv_espeak_without_voice():
    argv = SystemTtsProvider._build_argv("espeak-ng", "hi", None, "/tmp/o.wav")
    assert argv[:3] == ["espeak-ng", "-w", "/tmp/o.wav"]
    assert "-v" not in argv
    assert argv[-1] == "hi"


def test_synthesize_returns_wav_bytes(monkeypatch):
    monkeypatch.setattr(
        "yumi.core.features.tts.system_provider.resolve_system_command",
        lambda: "espeak",
    )

    def fake_run(argv, check, capture_output):
        out_path = argv[argv.index("-w") + 1]
        with open(out_path, "wb") as fh:
            fh.write(b"RIFFfake-wav-bytes")
        return None

    monkeypatch.setattr(subprocess, "run", fake_run)

    audio = asyncio.run(SystemTtsProvider().synthesize("hello", voice=None))
    assert isinstance(audio, SpeechAudio)
    assert audio.format == "wav"
    assert audio.data == b"RIFFfake-wav-bytes"


def test_synthesize_without_a_command_errors(monkeypatch):
    monkeypatch.setattr(
        "yumi.core.features.tts.system_provider.resolve_system_command",
        lambda: None,
    )
    with pytest.raises(TtsError):
        asyncio.run(SystemTtsProvider().synthesize("hello"))
