"""Shared STT data types and model metadata."""

from __future__ import annotations

from dataclasses import dataclass

WHISPER_MULTILINGUAL_MODELS = ("tiny", "base", "small", "medium", "large", "turbo")


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    language: str | None = None
    duration_seconds: float | None = None
