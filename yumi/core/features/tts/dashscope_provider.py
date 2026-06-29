"""Qwen3-TTS via the Alibaba Cloud DashScope API.

Light cloud backend: no GPU, no model download — just a ``DASHSCOPE_API_KEY``.
We request streaming, which returns base64-encoded PCM (24 kHz, 16-bit mono)
segments, and wrap the concatenated PCM into a WAV clip.
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
import wave
from typing import Any

from yumi.core.features.tts.base import TextToSpeechProvider, TtsError
from yumi.core.features.tts.types import SpeechAudio

DEFAULT_MODEL = "qwen3-tts-flash"
DEFAULT_VOICE = "Cherry"
# International (Singapore) endpoint; override with DASHSCOPE_BASE_URL for China.
DEFAULT_BASE_URL = "https://dashscope-intl.aliyuncs.com/api/v1"
_DASHSCOPE_SAMPLE_RATE = 24000


def _pcm16_to_wav(pcm: bytes, *, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)  # 16-bit
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buf.getvalue()


class DashScopeTtsProvider(TextToSpeechProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        voice: str | None = None,
        language: str | None = None,
        base_url: str | None = None,
    ):
        self._api_key = api_key or os.getenv("DASHSCOPE_API_KEY") or ""
        if not self._api_key:
            raise TtsError(
                "DashScope API key not set. Set DASHSCOPE_API_KEY (or tts_api_key in "
                "~/.yumi/config.json) to use the dashscope TTS provider."
            )
        self._model = model or DEFAULT_MODEL
        self._voice = voice or DEFAULT_VOICE
        self._language = language
        self._base_url = base_url or os.getenv("DASHSCOPE_BASE_URL") or DEFAULT_BASE_URL

    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        language: str | None = None,
    ) -> SpeechAudio:
        chosen_voice = voice or self._voice
        chosen_lang = language or self._language
        return await asyncio.to_thread(self._synthesize_blocking, text, chosen_voice, chosen_lang)

    def _synthesize_blocking(self, text: str, voice: str, language: str | None) -> SpeechAudio:
        pcm = bytearray()
        for chunk in self._stream_chunks(text, voice, language):
            encoded = self._chunk_audio_b64(chunk)
            if encoded:
                pcm += base64.b64decode(encoded)
        if not pcm:
            raise TtsError("DashScope returned no audio for the request.")
        wav = _pcm16_to_wav(bytes(pcm), sample_rate=_DASHSCOPE_SAMPLE_RATE)
        return SpeechAudio(data=wav, format="wav", sample_rate=_DASHSCOPE_SAMPLE_RATE, voice=voice)

    def _stream_chunks(self, text: str, voice: str, language: str | None):
        """The only part that imports the SDK and hits the network."""
        try:
            import dashscope
        except ImportError as exc:
            raise TtsError(
                "The 'dashscope' package is required for the DashScope TTS provider and ships with yumi. "
                "Reinstall with: pip install --force-reinstall yumi"
            ) from exc

        dashscope.base_http_api_url = self._base_url
        kwargs: dict[str, Any] = {
            "model": self._model,
            "api_key": self._api_key,
            "text": text,
            "voice": voice,
            "stream": True,
        }
        if language and language.strip().lower() != "auto":
            kwargs["language_type"] = language
        return dashscope.MultiModalConversation.call(**kwargs)

    @staticmethod
    def _chunk_audio_b64(chunk: Any) -> str | None:
        """Pull ``chunk.output.audio.data`` whether the SDK hands back attribute
        objects or plain dicts (the streaming response shape varies)."""

        def _get(obj: Any, key: str) -> Any:
            if obj is None:
                return None
            if isinstance(obj, dict):
                return obj.get(key)
            return getattr(obj, key, None)

        return _get(_get(_get(chunk, "output"), "audio"), "data")
