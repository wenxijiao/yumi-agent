"""Optional speech-to-text providers for Yumi."""

from yumi.core.features.stt.base import SpeechToTextProvider, SttError, SttNotConfiguredError
from yumi.core.features.stt.factory import create_stt_provider, transcribe_audio
from yumi.core.features.stt.types import WHISPER_MULTILINGUAL_MODELS, TranscriptionResult
from yumi.core.features.stt.whisper_provider import ensure_whisper_weights_cached

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
