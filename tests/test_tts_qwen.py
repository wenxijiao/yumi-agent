"""Local Qwen3-TTS provider — float->PCM conversion + factory wiring.

The model itself (torch/qwen-tts, GPU-only) is never loaded here; `_load_model`
is mocked so the conversion + plumbing can be tested on any machine.
"""

import asyncio
import io
import wave

import numpy as np
import pytest
from yumi.core.features.config.model import ModelConfig
from yumi.core.features.tts import create_tts_provider
from yumi.core.features.tts.base import TtsError
from yumi.core.features.tts.qwen_provider import QwenTtsProvider, _floats_to_pcm16


def test_floats_to_pcm16_scales_and_clips():
    pcm = _floats_to_pcm16([np.array([0.0, 1.0, -1.0, 0.5, 2.0], dtype=np.float32)])
    ints = np.frombuffer(pcm, dtype="<i2")
    assert ints[0] == 0
    assert ints[1] == 32767
    assert ints[2] == -32767
    assert abs(int(ints[3]) - 16383) <= 1
    assert ints[4] == 32767  # 2.0 clipped to 1.0


def test_floats_to_pcm16_empty_raises():
    with pytest.raises(TtsError):
        _floats_to_pcm16([])


def test_resolve_language_defaults_to_english():
    provider = QwenTtsProvider(language=None)
    assert provider._resolve_language(None) == "English"
    assert provider._resolve_language("auto") == "English"
    assert provider._resolve_language("Chinese") == "Chinese"


def test_factory_builds_qwen():
    provider = create_tts_provider(ModelConfig(tts_provider="qwen", tts_voice="Ryan"))
    assert isinstance(provider, QwenTtsProvider)


def test_synthesize_wraps_model_output(monkeypatch):
    provider = QwenTtsProvider(voice="Ryan")
    captured = {}

    class FakeModel:
        def generate_custom_voice(self, text, language, speaker):
            captured.update(text=text, language=language, speaker=speaker)
            return [np.array([0.0, 0.5, -0.5], dtype=np.float32)], 24000

    monkeypatch.setattr(provider, "_load_model", lambda: FakeModel())
    audio = asyncio.run(provider.synthesize("hello", voice="Ryan", language="English"))

    assert audio.format == "wav"
    assert audio.sample_rate == 24000
    assert captured == {"text": "hello", "language": "English", "speaker": "Ryan"}
    with wave.open(io.BytesIO(audio.data), "rb") as w:
        assert w.getframerate() == 24000
        assert w.getnchannels() == 1
