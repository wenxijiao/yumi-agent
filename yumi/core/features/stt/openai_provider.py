"""Cloud speech-to-text via the OpenAI transcription API.

Reuses the account's ``openai_api_key`` (the same key the chat/embedding
providers use) so there is nothing to download locally. The key is read lazily
on each call, so rotating it in config takes effect immediately.
"""

from __future__ import annotations

from yumi.core.features.stt.base import SpeechToTextProvider, SttError
from yumi.core.features.stt.types import TranscriptionResult

# Hosted transcription models, best default first.
OPENAI_STT_MODELS = ("gpt-4o-mini-transcribe", "gpt-4o-transcribe", "whisper-1")
DEFAULT_OPENAI_STT_MODEL = OPENAI_STT_MODELS[0]


class OpenAiSttProvider(SpeechToTextProvider):
    def __init__(self, *, model: str, language: str = "auto", base_url: str | None = None):
        self._model = model or DEFAULT_OPENAI_STT_MODEL
        self._language = (language or "auto").strip().lower()
        self._base_url = base_url

    async def transcribe(
        self,
        audio: bytes,
        *,
        filename: str,
        language: str | None = None,
    ) -> TranscriptionResult:
        try:
            from openai import AsyncOpenAI
        except Exception as exc:  # pragma: no cover - openai is a core dependency
            raise SttError("The `openai` package is required for cloud transcription.") from exc

        from yumi.core.features.config.credentials import get_api_credentials

        creds = get_api_credentials()
        api_key = creds.get("openai_api_key")
        if not api_key:
            raise SttError("Cloud transcription needs an OpenAI API key. Set OPENAI_API_KEY or run `yumi --setup`.")

        lang = (language or self._language or "auto").strip().lower()
        request: dict = {"model": self._model, "file": (filename, audio)}
        if lang and lang != "auto":
            request["language"] = lang

        # Honor a configured OpenAI-compatible endpoint (proxy / Azure) the same way
        # the chat provider does, so STT and chat share one base URL.
        base_url = self._base_url or creds.get("openai_base_url")
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        try:
            result = await client.audio.transcriptions.create(**request)
        except Exception as exc:
            raise SttError(f"OpenAI transcription failed: {exc}") from exc
        finally:
            close = getattr(client, "close", None)
            if close is not None:
                try:
                    await close()
                except Exception:
                    pass

        text = (getattr(result, "text", None) or "").strip()
        return TranscriptionResult(text=text, language=lang if lang != "auto" else None)
