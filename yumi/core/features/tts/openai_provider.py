"""Cloud text-to-speech via OpenAI (``openai`` is a core dependency).

No model download — reuses the account's ``openai_api_key``. Returns WAV so the
audio plays through the same local backends as every other provider (winsound on
Windows, aplay/paplay on Linux, afplay on macOS), which assume WAV.
"""

from __future__ import annotations

from yumi.core.features.tts.base import TextToSpeechProvider, TtsError
from yumi.core.features.tts.types import SpeechAudio

OPENAI_TTS_MODELS = ("gpt-4o-mini-tts", "tts-1", "tts-1-hd")
OPENAI_TTS_VOICES = ("alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer")
# The legacy tts-1 / tts-1-hd models only accept these 6 original voices.
_CLASSIC_VOICES = ("alloy", "echo", "fable", "onyx", "nova", "shimmer")
DEFAULT_OPENAI_TTS_MODEL = OPENAI_TTS_MODELS[0]
DEFAULT_OPENAI_TTS_VOICE = "alloy"


class OpenAiTtsProvider(TextToSpeechProvider):
    def __init__(self, *, model: str | None = None, voice: str | None = None, language: str | None = None):
        self._model = model or DEFAULT_OPENAI_TTS_MODEL
        self._voice = voice or DEFAULT_OPENAI_TTS_VOICE
        self._language = language

    async def synthesize(
        self,
        text: str,
        *,
        voice: str | None = None,
        language: str | None = None,
    ) -> SpeechAudio:
        try:
            from openai import AsyncOpenAI
        except Exception as exc:  # pragma: no cover - openai is a core dependency
            raise TtsError("The `openai` package is required for OpenAI TTS.") from exc

        from yumi.core.features.config.credentials import get_api_credentials

        api_key = get_api_credentials().get("openai_api_key")
        if not api_key:
            raise TtsError("OpenAI TTS needs an OpenAI API key. Set OPENAI_API_KEY or run `yumi --setup`.")

        chosen_voice = voice or self._voice
        if self._model.startswith("tts-1") and chosen_voice not in _CLASSIC_VOICES:
            chosen_voice = DEFAULT_OPENAI_TTS_VOICE
        client = AsyncOpenAI(api_key=api_key)
        try:
            response = await client.audio.speech.create(
                model=self._model,
                voice=chosen_voice,
                input=text,
                response_format="wav",
            )
            data = _response_bytes(response)
        except Exception as exc:
            raise TtsError(f"OpenAI TTS failed: {exc}") from exc
        finally:
            close = getattr(client, "close", None)
            if close is not None:
                try:
                    await close()
                except Exception:
                    pass

        if not data:
            raise TtsError("OpenAI returned no audio for the request.")
        return SpeechAudio(data=data, format="wav", voice=chosen_voice)


def _response_bytes(response) -> bytes:
    """Read bytes from the binary speech response across openai SDK versions."""
    content = getattr(response, "content", None)
    if isinstance(content, (bytes, bytearray)):
        return bytes(content)
    read = getattr(response, "read", None)
    if read is not None:
        result = read()
        if isinstance(result, (bytes, bytearray)):
            return bytes(result)
    return bytes(content) if content else b""
