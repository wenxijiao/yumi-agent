"""Cloud speech-to-text via Google Gemini (``google-genai``, a core dependency).

Transcribes by handing the audio to a Gemini model as inline data with a
"transcribe verbatim" instruction. Reuses the account's ``gemini_api_key``.
"""

from __future__ import annotations

import asyncio
import mimetypes

from yumi.core.features.stt.base import SpeechToTextProvider, SttError
from yumi.core.features.stt.types import TranscriptionResult

GEMINI_STT_MODELS = ("gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite")
DEFAULT_GEMINI_STT_MODEL = GEMINI_STT_MODELS[0]

_PROMPT = "Transcribe the spoken audio verbatim. Return only the transcript text, with no commentary."


# Gemini's documented inline-audio MIME allowlist, keyed by file suffix. We map
# by suffix FIRST: the real callers feed ``.wav`` (voice loop) and ``.m4a`` (LINE),
# and ``mimetypes.guess_type`` returns non-canonical strings for those on some
# platforms (e.g. ``audio/x-wav``, ``audio/mp4a-latm``) that Gemini rejects with a
# 400. Only suffixes Gemini accepts are listed; ``.m4a`` carries AAC, so it maps to
# ``audio/aac``.
_GEMINI_AUDIO_MIME: dict[str, str] = {
    ".ogg": "audio/ogg",
    ".oga": "audio/ogg",
    ".opus": "audio/ogg",
    ".mp3": "audio/mp3",
    ".wav": "audio/wav",
    ".m4a": "audio/aac",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".aiff": "audio/aiff",
    ".aif": "audio/aiff",
}
_GEMINI_ACCEPTED_MIME = frozenset(_GEMINI_AUDIO_MIME.values())


def _guess_audio_mime(filename: str) -> str:
    lower = (filename or "").lower()
    for suffix, value in _GEMINI_AUDIO_MIME.items():
        if lower.endswith(suffix):
            return value
    # Unknown suffix: trust guess_type only if it lands on a Gemini-accepted type,
    # else default to ogg (the safest broadly-supported container).
    mime, _encoding = mimetypes.guess_type(filename)
    if mime in _GEMINI_ACCEPTED_MIME:
        return mime
    return "audio/ogg"


class GeminiSttProvider(SpeechToTextProvider):
    def __init__(self, *, model: str, language: str = "auto"):
        self._model = model or DEFAULT_GEMINI_STT_MODEL
        self._language = (language or "auto").strip().lower()

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
            from google import genai
            from google.genai import types
        except Exception as exc:  # pragma: no cover - google-genai is a core dependency
            raise SttError("The 'google-genai' package is required for Gemini transcription.") from exc

        from yumi.core.features.config.credentials import get_api_credentials

        api_key = get_api_credentials().get("gemini_api_key")
        if not api_key:
            raise SttError("Cloud transcription needs a Gemini API key. Set GEMINI_API_KEY or run `yumi --setup`.")

        lang = (language or self._language or "auto").strip().lower()
        prompt = _PROMPT if lang in ("", "auto") else f"{_PROMPT} The audio language is {lang}."

        client = genai.Client(api_key=api_key)
        try:
            response = client.models.generate_content(
                model=self._model,
                contents=[
                    types.Part(inline_data=types.Blob(mime_type=_guess_audio_mime(filename), data=audio)),
                    types.Part(text=prompt),
                ],
            )
        except Exception as exc:
            raise SttError(f"Gemini transcription failed: {exc}") from exc

        text = (getattr(response, "text", None) or "").strip()
        return TranscriptionResult(text=text, language=lang if lang not in ("", "auto") else None)
