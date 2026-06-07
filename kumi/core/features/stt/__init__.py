"""Optional speech-to-text providers for Kumi."""

from kumi.core.features.stt.base import SpeechToTextProvider, SttError, SttNotConfiguredError
from kumi.core.features.stt.factory import create_stt_provider, transcribe_audio
from kumi.core.features.stt.types import WHISPER_MULTILINGUAL_MODELS, TranscriptionResult
from kumi.core.features.stt.whisper_provider import ensure_whisper_weights_cached

__all__ = [
    "SpeechToTextProvider",
    "SttError",
    "SttNotConfiguredError",
    "TranscriptionResult",
    "WHISPER_MULTILINGUAL_MODELS",
    "create_stt_provider",
    "transcribe_audio",
    "ensure_whisper_weights_cached",
]
