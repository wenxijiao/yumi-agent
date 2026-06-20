"""Zero-dependency TTS via the OS speech command.

macOS ships ``say``; most Linux distros have ``espeak`` / ``espeak-ng``. This is
the always-available default so spoken replies work without a GPU, an API key,
or a heavy model download. Quality is modest — the qwen / dashscope providers
are the upgrade path.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile

from yumi.core.features.tts.base import TextToSpeechProvider, TtsError
from yumi.core.features.tts.types import SpeechAudio

_SAMPLE_RATE = 22050


def resolve_system_command() -> str | None:
    """Name of an available OS speech command, or None."""
    if sys.platform == "darwin" and shutil.which("say"):
        return "say"
    for candidate in ("espeak-ng", "espeak"):
        if shutil.which(candidate):
            return candidate
    return None


class SystemTtsProvider(TextToSpeechProvider):
    def __init__(self, *, voice: str | None = None):
        self._voice = voice

    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        language: str | None = None,  # noqa: ARG002 - OS voices already encode language
    ) -> SpeechAudio:
        return await asyncio.to_thread(self._synthesize_blocking, text, voice or self._voice)

    def _synthesize_blocking(self, text: str, voice: str | None) -> SpeechAudio:
        command = resolve_system_command()
        if not command:
            raise TtsError(
                "No system TTS command found. Install one (Debian/Ubuntu: "
                "`sudo apt install espeak-ng`) or choose the dashscope/qwen provider."
            )
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            path = tmp.name
        try:
            argv = self._build_argv(command, text, voice, path)
            try:
                subprocess.run(argv, check=True, capture_output=True)
            except (subprocess.CalledProcessError, OSError) as exc:
                raise TtsError(f"System TTS command failed: {exc}") from exc
            with open(path, "rb") as fh:
                data = fh.read()
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        return SpeechAudio(data=data, format="wav", sample_rate=_SAMPLE_RATE, voice=voice)

    @staticmethod
    def _build_argv(command: str, text: str, voice: str | None, out_path: str) -> list[str]:
        if command == "say":  # macOS
            argv = ["say", "-o", out_path, "--file-format=WAVE", f"--data-format=LEI16@{_SAMPLE_RATE}"]
            if voice:
                argv += ["-v", voice]
            argv.append(text)
            return argv
        # espeak / espeak-ng
        argv = [command, "-w", out_path]
        if voice:
            argv += ["-v", voice]
        argv.append(text)
        return argv
