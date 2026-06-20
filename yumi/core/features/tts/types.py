"""Shared TTS data types."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpeechAudio:
    """A synthesized audio clip plus the metadata a caller needs to play or
    re-encode it (e.g. a bridge turning it into a Telegram voice note)."""

    data: bytes
    format: str  # "wav" | "mp3" | "ogg" | "pcm"
    sample_rate: int | None = None
    voice: str | None = None
