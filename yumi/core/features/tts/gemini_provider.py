"""Gemini text-to-speech provider."""

from __future__ import annotations

import asyncio
import base64
import io
import os
import wave
from typing import Any

from yumi.core.features.tts.base import TextToSpeechProvider, TtsError
from yumi.core.features.tts.types import SpeechAudio

DEFAULT_MODEL = "gemini-3.1-flash-tts-preview"
DEFAULT_VOICE = "Kore"
MODEL_CHOICES = (
    "gemini-3.1-flash-tts-preview",
    "gemini-2.5-flash-preview-tts",
    "gemini-2.5-pro-preview-tts",
)
VOICE_CHOICES = (
    "Zephyr",
    "Puck",
    "Charon",
    "Kore",
    "Fenrir",
    "Leda",
    "Orus",
    "Aoede",
    "Callirrhoe",
    "Autonoe",
    "Enceladus",
    "Iapetus",
    "Umbriel",
    "Algieba",
    "Despina",
    "Erinome",
    "Algenib",
    "Rasalgethi",
    "Laomedeia",
    "Achernar",
    "Alnilam",
    "Schedar",
    "Gacrux",
    "Pulcherrima",
    "Achird",
    "Zubenelgenubi",
    "Vindemiatrix",
    "Sadachbia",
    "Sadaltager",
    "Sulafat",
)
_SAMPLE_RATE = 24000


def _pcm16_to_wav(pcm: bytes, *, sample_rate: int = _SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buf.getvalue()


def _inline_audio_bytes(response: Any) -> bytes:
    try:
        data = response.candidates[0].content.parts[0].inline_data.data
    except Exception as exc:
        raise TtsError("Gemini TTS returned no inline audio.") from exc
    if isinstance(data, bytes):
        return data
    if isinstance(data, bytearray):
        return bytes(data)
    if isinstance(data, str):
        try:
            return base64.b64decode(data)
        except Exception as exc:
            raise TtsError("Gemini TTS returned invalid base64 audio.") from exc
    raise TtsError("Gemini TTS returned an unsupported audio payload.")


class GeminiTtsProvider(TextToSpeechProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        voice: str | None = None,
        language: str | None = None,
    ):
        try:
            from google import genai
        except ImportError as exc:
            raise TtsError(
                "The 'google-genai' package ships with yumi but is missing here. "
                "Reinstall with: pip install --force-reinstall yumi"
            ) from exc

        resolved_key = api_key or os.getenv("GEMINI_API_KEY") or ""
        if not resolved_key:
            raise TtsError("Gemini API key not set. Set GEMINI_API_KEY or save gemini_api_key in ~/.yumi/config.json.")

        self._client = genai.Client(api_key=resolved_key)
        self._model = model or DEFAULT_MODEL
        self._voice = voice or DEFAULT_VOICE
        self._language = language or "auto"

    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        language: str | None = None,
    ) -> SpeechAudio:
        return await asyncio.to_thread(self._synthesize_sync, text, voice or self._voice, language or self._language)

    def _synthesize_sync(self, text: str, voice: str, language: str | None) -> SpeechAudio:
        from google.genai import types

        speech_kwargs: dict[str, Any] = {
            "voice_config": types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice),
            )
        }
        if language and language.strip().lower() != "auto":
            speech_kwargs["language_code"] = language.strip()
        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=text,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(**speech_kwargs),
                ),
            )
        except Exception as exc:
            raise TtsError(f"Gemini TTS failed: {exc}") from exc
        pcm = _inline_audio_bytes(response)
        if not pcm:
            raise TtsError("Gemini TTS returned no audio.")
        return SpeechAudio(data=_pcm16_to_wav(pcm), format="wav", sample_rate=_SAMPLE_RATE, voice=voice)
