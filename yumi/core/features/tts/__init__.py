"""Text-to-speech (spoken replies). Disabled by default; configured via `yumi --setup`."""

from yumi.core.features.tts.base import TextToSpeechProvider, TtsError, TtsNotConfiguredError
from yumi.core.features.tts.factory import create_tts_provider
from yumi.core.features.tts.types import SpeechAudio

__all__ = [
    "SpeechAudio",
    "TextToSpeechProvider",
    "TtsError",
    "TtsNotConfiguredError",
    "create_tts_provider",
]
