"""xAI/Grok text-to-speech provider."""

from __future__ import annotations

import os
from typing import Any

import httpx
from yumi.core.features.tts.base import TextToSpeechProvider, TtsError
from yumi.core.features.tts.types import SpeechAudio

DEFAULT_BASE_URL = "https://api.x.ai/v1"
DEFAULT_VOICE = "eve"
VOICE_CHOICES = ("eve", "ara", "rex", "sal", "leo")


def _endpoint(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/tts"


def _error_detail(response: httpx.Response) -> str:
    try:
        payload: Any = response.json()
    except Exception:
        payload = response.text
    return str(payload)[:500]


class GrokTtsProvider(TextToSpeechProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        voice: str | None = None,
        language: str | None = None,
    ):
        self._api_key = api_key or os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY") or ""
        if not self._api_key:
            raise TtsError("Grok API key not set. Set XAI_API_KEY or save grok_api_key in ~/.yumi/config.json.")
        self._base_url = base_url or os.getenv("XAI_BASE_URL") or os.getenv("GROK_BASE_URL") or DEFAULT_BASE_URL
        self._voice = voice or DEFAULT_VOICE
        self._language = language or "auto"

    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        language: str | None = None,
    ) -> SpeechAudio:
        chosen_voice = voice or self._voice
        chosen_language = language or self._language
        payload = {"text": text, "voice_id": chosen_voice}
        if chosen_language and chosen_language.strip().lower() != "auto":
            payload["language"] = chosen_language.strip()
        else:
            payload["language"] = "en"
        timeout = httpx.Timeout(120.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                _endpoint(self._base_url),
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        if response.status_code >= 400:
            raise TtsError(f"Grok TTS failed ({response.status_code}): {_error_detail(response)}")
        if not response.content:
            raise TtsError("Grok TTS returned no audio.")
        return SpeechAudio(data=response.content, format="mp3", sample_rate=None, voice=chosen_voice)
