"""Factory helpers for configured STT providers."""

from __future__ import annotations

from kumi.core.features.config import load_model_config
from kumi.core.features.config.model import RECOMMENDED_STT_MODEL, ModelConfig
from kumi.core.features.stt.base import SpeechToTextProvider, SttError, SttNotConfiguredError
from kumi.core.features.stt.types import TranscriptionResult
from kumi.core.features.stt.whisper_provider import WhisperSttProvider

_PROVIDER_CACHE: tuple[tuple[str, str, str, str, str], SpeechToTextProvider] | None = None


def create_stt_provider(config: ModelConfig | None = None) -> SpeechToTextProvider:
    cfg = config or load_model_config()
    provider = (cfg.stt_provider or "disabled").strip().lower()
    if provider in ("", "disabled", "none", "off"):
        raise SttNotConfiguredError("STT is not enabled. Run `kumi --setup` to enable voice transcription.")
    if provider != "whisper":
        raise SttError(f"Unsupported STT provider: {cfg.stt_provider!r}")
    backend = (cfg.stt_backend or "faster-whisper").strip().lower()
    if backend != "faster-whisper":
        raise SttError(f"Unsupported Whisper STT backend: {cfg.stt_backend!r}")
    return WhisperSttProvider(
        model=cfg.stt_model or RECOMMENDED_STT_MODEL,
        model_dir=cfg.stt_model_dir,
        language=cfg.stt_language or "auto",
    )


def _cache_key(config: ModelConfig) -> tuple[str, str, str, str, str]:
    return (
        config.stt_provider or "disabled",
        config.stt_backend or "faster-whisper",
        config.stt_model or "",
        config.stt_model_dir or "",
        config.stt_language or "auto",
    )


async def transcribe_audio(
    audio: bytes,
    *,
    filename: str,
    language: str | None = None,
    config: ModelConfig | None = None,
) -> TranscriptionResult:
    global _PROVIDER_CACHE
    cfg = config or load_model_config()
    key = _cache_key(cfg)
    if _PROVIDER_CACHE is None or _PROVIDER_CACHE[0] != key:
        _PROVIDER_CACHE = (key, create_stt_provider(cfg))
    return await _PROVIDER_CACHE[1].transcribe(audio, filename=filename, language=language)
