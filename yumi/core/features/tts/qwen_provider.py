"""Qwen3-TTS run locally via the ``qwen-tts`` package.

This is the self-hosted alternative to the DashScope API provider. It loads the
model with ``transformers``/``torch``. CUDA/NVIDIA is the fastest and most
reliable path; Apple MPS can work on some Apple Silicon Macs with more
conservative loading settings, but is still slower/more experimental. The model
is loaded lazily on first synthesis so importing this module stays cheap.
"""

from __future__ import annotations

import asyncio
import io
import wave
from typing import Any

from yumi.core.features.config.paths import QWEN_TTS_MODELS_DIR
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
        self._device = device  # None -> auto-detect at load time
        self._model: Any = None  # lazily loaded

    @staticmethod
    def _auto_device(torch: Any) -> str:
        """Pick the best available device: CUDA, then Apple MPS, then CPU."""
        try:
            if torch.cuda.is_available():
                return "cuda:0"
            mps = getattr(torch.backends, "mps", None)
            if mps is not None and mps.is_available():
                return "mps"
        except Exception:
            pass
        return "cpu"

    @staticmethod
    def _load_kwargs(torch: Any, device: str) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"device_map": device}
        if device.startswith("cuda"):
            kwargs["dtype"] = torch.bfloat16
        else:
            # MPS/CPU are more fragile with bf16/flash attention. SDPA + fp32 is
            # slower, but avoids the most common non-CUDA load failures.
            kwargs["dtype"] = torch.float32
            kwargs["attn_implementation"] = "sdpa"
        return kwargs

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            import torch
            from qwen_tts import Qwen3TTSModel
        except ImportError as exc:
            raise TtsError(
                "qwen-tts (and PyTorch) are required for the local Qwen3-TTS provider. "
                "Install PyTorch for your GPU from https://pytorch.org/get-started/locally/ , "
                "then: pip install 'yumi-agent[tts-local]'."
            ) from exc
        device = self._device or self._auto_device(torch)
        QWEN_TTS_MODELS_DIR.mkdir(parents=True, exist_ok=True)
        self._model = Qwen3TTSModel.from_pretrained(
            self._model_name,
            cache_dir=str(QWEN_TTS_MODELS_DIR),
            **self._load_kwargs(torch, device),
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
