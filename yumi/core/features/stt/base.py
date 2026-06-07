"""Base classes and errors for speech-to-text backends."""

from __future__ import annotations

from abc import ABC, abstractmethod

from yumi.core.features.stt.types import TranscriptionResult


class SttError(RuntimeError):
    """Raised when STT cannot process an audio request."""


class SttNotConfiguredError(SttError):
    """Raised when voice input is used before STT is enabled."""


class SpeechToTextProvider(ABC):
    @abstractmethod
    async def transcribe(
        self,
        audio: bytes,
        *,
        filename: str,
        language: str | None = None,
    ) -> TranscriptionResult:
        """Return text for an audio payload."""
