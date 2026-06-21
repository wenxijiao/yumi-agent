"""Qwen3-TTS run locally via the ``qwen-tts`` package.

This is the self-hosted alternative to the DashScope API provider. It loads the
model with ``transformers``/``torch`` and realistically needs an NVIDIA GPU —
on CPU / Apple Silicon it will be very slow or fail to load FlashAttention. The
model is loaded lazily on first synthesis so importing this module stays cheap.
"""

from __future__ import annotations

import asyncio
import io
import wave
from typing import Any

from yumi.core.features.tts.base import TextToSpeechProvider, TtsError
from yumi.core.features.tts.types import SpeechAudio

DEFAULT_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
DEFAULT_SPEAKER = "Ryan"
DEFAULT_LANGUAGE = "English"


def _floats_to_pcm16(wavs: list[Any]) -> bytes:
    import numpy as np

    arrays = [np.asarray(w, dtype=np.float32).reshape(-1) for w in wavs if w is not None]
    if not arrays:
        raise TtsError("qwen-tts returned no audio.")
    audio = np.concatenate(arrays)
    audio = np.clip(audio, -1.0, 1.0)
    return (audio * 32767.0).astype("<i2").tobytes()


def _pcm16_to_wav(pcm: bytes, *, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buf.getvalue()


class QwenTtsProvider(TextToSpeechProvider):
    def __init__(
        self,
        *,
        model: str | None = None,
        voice: str | None = None,
        language: str | None = None,
        device: str | None = None,
    ):
        self._model_name = model or DEFAULT_MODEL
        self._voice = voice or DEFAULT_SPEAKER
        self._language = language
        self._device = device or "cuda:0"
        self._model: Any = None  # lazily loaded

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            import torch
            from qwen_tts import Qwen3TTSModel
        except ImportError as exc:
            raise TtsError(
                "qwen-tts is required for the local Qwen3-TTS provider. Install it with: "
                "pip install 'yumi-agent[tts-local]' (realistically needs a CUDA GPU)."
            ) from exc
        self._model = Qwen3TTSModel.from_pretrained(
            self._model_name,
            device_map=self._device,
            dtype=torch.bfloat16,
        )
        return self._model

    def _resolve_language(self, language: str | None) -> str:
        candidate = (language or self._language or "").strip()
        if not candidate or candidate.lower() == "auto":
            return DEFAULT_LANGUAGE
        return candidate

    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        language: str | None = None,
    ) -> SpeechAudio:
        return await asyncio.to_thread(self._synthesize_blocking, text, voice or self._voice, language)

    def _synthesize_blocking(self, text: str, voice: str, language: str | None) -> SpeechAudio:
        model = self._load_model()
        wavs, sample_rate = model.generate_custom_voice(
            text=text,
            language=self._resolve_language(language),
            speaker=voice,
        )
        pcm = _floats_to_pcm16(list(wavs))
        wav_bytes = _pcm16_to_wav(pcm, sample_rate=int(sample_rate))
        return SpeechAudio(data=wav_bytes, format="wav", sample_rate=int(sample_rate), voice=voice)
