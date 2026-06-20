"""Base classes and errors for text-to-speech backends."""

from __future__ import annotations

from abc import ABC, abstractmethod

from yumi.core.features.tts.types import SpeechAudio


class TtsError(RuntimeError):
    """Raised when TTS cannot synthesize a request."""


class TtsNotConfiguredError(TtsError):
    """Raised when spoken output is used before TTS is enabled."""


class TextToSpeechProvider(ABC):
    @abstractmethod
    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        language: str | None = None,
    ) -> SpeechAudio:
        """Return synthesized audio for *text*."""
