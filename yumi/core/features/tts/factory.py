"""Factory helpers for the configured TTS provider."""

from __future__ import annotations

from yumi.core.features.config import load_model_config
from yumi.core.features.config.model import ModelConfig
from yumi.core.features.tts.base import TextToSpeechProvider, TtsError, TtsNotConfiguredError
from yumi.core.features.tts.system_provider import SystemTtsProvider

_DISABLED = ("", "disabled", "none", "off")


def create_tts_provider(config: ModelConfig | None = None) -> TextToSpeechProvider:
    cfg = config or load_model_config()
    provider = (cfg.tts_provider or "disabled").strip().lower()
    if provider in _DISABLED:
        raise TtsNotConfiguredError("TTS is not enabled. Run `yumi --setup` to enable spoken replies.")
    if provider == "system":
        return SystemTtsProvider(voice=cfg.tts_voice)
    if provider == "dashscope":
        from yumi.core.features.tts.dashscope_provider import DashScopeTtsProvider

        return DashScopeTtsProvider(
            api_key=cfg.tts_api_key,
            model=cfg.tts_model,
            voice=cfg.tts_voice,
            language=cfg.tts_language,
        )
    if provider == "qwen":
        from yumi.core.features.tts.qwen_provider import QwenTtsProvider

        return QwenTtsProvider(model=cfg.tts_model, voice=cfg.tts_voice, language=cfg.tts_language)
    raise TtsError(f"Unsupported TTS provider: {cfg.tts_provider!r}")
