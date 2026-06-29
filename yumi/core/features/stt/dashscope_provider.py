"""Cloud speech-to-text via Alibaba Cloud DashScope (Qwen ASR).

Uses the ``dashscope`` SDK from the base install. The audio bytes are written to
a short-lived temp file and handed to the multimodal ASR model; the response
shape is read defensively (attribute objects or plain dicts), mirroring the
DashScope TTS provider.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from typing import Any

from yumi.core.features.stt.base import SpeechToTextProvider, SttError
from yumi.core.features.stt.types import TranscriptionResult

DASHSCOPE_STT_MODELS = ("qwen3-asr-flash",)
DEFAULT_DASHSCOPE_STT_MODEL = DASHSCOPE_STT_MODELS[0]
# International (Singapore) endpoint; override with DASHSCOPE_BASE_URL for China.
DEFAULT_BASE_URL = "https://dashscope-intl.aliyuncs.com/api/v1"

# DashScope ASR wants short ISO codes (zh/en/ja/...). Map common names/locales;
# anything unrecognized falls back to auto-detect (no language hint).
_DASHSCOPE_LANGS = {
    "zh": "zh",
    "chinese": "zh",
    "mandarin": "zh",
    "en": "en",
    "english": "en",
    "ja": "ja",
    "japanese": "ja",
    "ko": "ko",
    "korean": "ko",
    "es": "es",
    "spanish": "es",
    "fr": "fr",
    "french": "fr",
    "de": "de",
    "german": "de",
    "it": "it",
    "italian": "it",
    "pt": "pt",
    "portuguese": "pt",
    "ru": "ru",
    "russian": "ru",
    "ar": "ar",
    "arabic": "ar",
}


def _dashscope_lang(language: str | None) -> str | None:
    value = (language or "").strip().lower()
    if value in ("", "auto"):
        return None
    return _DASHSCOPE_LANGS.get(value) or _DASHSCOPE_LANGS.get(value.split("-")[0])


def _get(obj: Any, key: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _extract_text(response: Any) -> str:
    """Pull the transcript from a Qwen ASR multimodal response.

    The content is typically ``output.choices[0].message.content`` as a list of
    ``{"text": ...}`` parts; handle attribute/dict shapes and string content.
    """
    output = _get(response, "output")
    choices = _get(output, "choices")
    if not choices:
        return ""
    message = _get(choices[0], "message")
    content = _get(message, "content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [str(_get(part, "text") or "") for part in content]
        return "".join(parts).strip()
    return ""


class DashScopeSttProvider(SpeechToTextProvider):
    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        language: str = "auto",
        base_url: str | None = None,
    ):
        self._model = model or DEFAULT_DASHSCOPE_STT_MODEL
        self._api_key = api_key or os.getenv("DASHSCOPE_API_KEY") or ""
        self._language = (language or "auto").strip().lower()
        self._base_url = base_url or os.getenv("DASHSCOPE_BASE_URL") or DEFAULT_BASE_URL

    async def transcribe(
        self,
        audio: bytes,
        *,
        filename: str,
        language: str | None = None,
    ) -> TranscriptionResult:
        return await asyncio.to_thread(self._transcribe_blocking, audio, filename, language)

    def _transcribe_blocking(self, audio: bytes, filename: str, language: str | None) -> TranscriptionResult:
        try:
            import dashscope
        except ImportError as exc:
            raise SttError(
                "The 'dashscope' package is required for DashScope transcription and ships with yumi-agent. "
                "Reinstall with: pip install --force-reinstall yumi-agent"
            ) from exc

        if not self._api_key:
            raise SttError(
                "DashScope API key not set. Set DASHSCOPE_API_KEY (or tts_api_key in "
                "~/.yumi/config.json) to use the DashScope transcription provider."
            )

        suffix = os.path.splitext(filename)[1] or ".wav"
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        try:
            tmp.write(audio)
            tmp.close()
            dashscope.base_http_api_url = self._base_url
            messages = [{"role": "user", "content": [{"audio": f"file://{tmp.name}"}]}]
            kwargs: dict[str, Any] = {
                "model": self._model,
                "api_key": self._api_key,
                "messages": messages,
                "result_format": "message",
            }
            code = _dashscope_lang(language or self._language)
            if code:
                kwargs["asr_options"] = {"language": code}
            try:
                response = dashscope.MultiModalConversation.call(**kwargs)
            except Exception as exc:
                raise SttError(f"DashScope transcription failed: {exc}") from exc
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

        status = _get(response, "status_code")
        if status is not None and status != 200:
            raise SttError(f"DashScope transcription failed ({status}): {_get(response, 'message')}")
        text = _extract_text(response)
        lang = (language or self._language or "auto").strip().lower()
        return TranscriptionResult(text=text, language=lang if lang not in ("", "auto") else None)
