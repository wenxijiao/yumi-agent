"""Play a synthesized clip on the local machine + a high-level speak() helper.

Playback shells out to whatever audio player the OS ships (macOS ``afplay``;
Linux ``paplay`` / ``aplay`` / ``ffplay``) so it needs no Python audio deps.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile

from yumi.core.features.config.model import ModelConfig
from yumi.core.features.tts.factory import create_tts_provider
from yumi.core.features.tts.types import SpeechAudio


class PlaybackError(RuntimeError):
    """Raised when no audio player is available or playback fails."""


def resolve_player() -> list[str] | None:
    """Argv prefix for an available audio player, or None."""
    if sys.platform == "darwin" and shutil.which("afplay"):
        return ["afplay"]
    if shutil.which("paplay"):
        return ["paplay"]
    if shutil.which("aplay"):
        return ["aplay", "-q"]
    if shutil.which("ffplay"):
        return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"]
    return None


def play_audio(audio: SpeechAudio) -> None:
    player = resolve_player()
    if not player:
        raise PlaybackError(
            "No audio player found. Install one (Linux: `sudo apt install pulseaudio-utils` "
            "for paplay, or alsa-utils for aplay)."
        )
    with tempfile.NamedTemporaryFile(suffix=f".{audio.format or 'wav'}", delete=False) as tmp:
        tmp.write(audio.data)
        path = tmp.name
    try:
        subprocess.run([*player, path], check=True, capture_output=True)
    except (subprocess.CalledProcessError, OSError) as exc:
        raise PlaybackError(f"Audio playback failed: {exc}") from exc
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


async def synthesize(text: str, *, config: ModelConfig | None = None) -> SpeechAudio:
    provider = create_tts_provider(config)
    return await provider.synthesize(text)


async def synthesize_with_fallback(text: str, *, config: ModelConfig | None = None) -> SpeechAudio:
    """Synthesize via the configured provider, falling back to the OS system voice.

    Used where audio is always expected (voice mode, a bridge in voice-reply
    mode): if TTS isn't configured we still produce a clip with the system voice
    rather than going silent.
    """
    from yumi.core.features.tts.base import TtsNotConfiguredError
    from yumi.core.features.tts.system_provider import SystemTtsProvider

    try:
        provider = create_tts_provider(config)
    except TtsNotConfiguredError:
        provider = SystemTtsProvider()
    return await provider.synthesize(text)


def speak(text: str, *, config: ModelConfig | None = None) -> None:
    """Synthesize *text* with the configured TTS provider and play it."""
    audio = asyncio.run(synthesize(text, config=config))
    play_audio(audio)
