"""xAI/Grok speech-to-text provider."""

from __future__ import annotations

import mimetypes
import os
from typing import Any

import httpx
from yumi.core.features.stt.base import SpeechToTextProvider, SttError
from yumi.core.features.stt.types import TranscriptionResult

DEFAULT_BASE_URL = "https://api.x.ai/v1"


def _endpoint(base_url: str) -> str:
    return f"{base_url.rstrip('/')}/stt"


def _error_detail(response: httpx.Response) -> str:
    try:
        payload: Any = response.json()
    except Exception:
        payload = response.text
    return str(payload)[:500]


class GrokSttProvider(SpeechToTextProvider):
    def __init__(self, *, api_key: str | None = None, base_url: str | None = None):
        self._api_key = api_key or os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY") or ""
        if not self._api_key:
            raise SttError("Grok API key not set. Set XAI_API_KEY or save grok_api_key in ~/.yumi/config.json.")
        self._base_url = base_url or os.getenv("XAI_BASE_URL") or os.getenv("GROK_BASE_URL") or DEFAULT_BASE_URL

    async def transcribe(
        self,
        audio: bytes,
        *,
        filename: str,
        language: str | None = None,
    ) -> TranscriptionResult:
        del language  # xAI's documented batch endpoint auto-detects language.
        mime = mimetypes.guess_type(filename or "")[0] or "application/octet-stream"
        files = {"file": (filename or "audio.wav", audio, mime)}
        timeout = httpx.Timeout(120.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                _endpoint(self._base_url),
                headers={"Authorization": f"Bearer {self._api_key}"},
                files=files,
            )
        if response.status_code >= 400:
            raise SttError(f"Grok STT failed ({response.status_code}): {_error_detail(response)}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise SttError("Grok STT returned invalid JSON.") from exc
        text = str(payload.get("text") or "").strip()
        if not text:
            raise SttError("Grok STT returned no transcript.")
        return TranscriptionResult(
            text=text, language=payload.get("language"), duration_seconds=payload.get("duration")
        )
