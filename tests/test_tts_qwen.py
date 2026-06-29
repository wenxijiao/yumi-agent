"""Local Qwen3-TTS provider — float->PCM conversion + factory wiring.

The model itself (torch/qwen-tts, GPU-only) is never loaded here; `_load_model`
is mocked so the conversion + plumbing can be tested on any machine.
"""

import asyncio
import io
import sys
import types
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


def test_auto_device_prefers_cuda_then_mps_then_cpu():
    import types

    def fake_torch(cuda: bool, mps: bool):
        return types.SimpleNamespace(
            cuda=types.SimpleNamespace(is_available=lambda: cuda),
            backends=types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: mps)),
        )

    assert QwenTtsProvider._auto_device(fake_torch(True, True)) == "cuda:0"
    assert QwenTtsProvider._auto_device(fake_torch(False, True)) == "mps"
    assert QwenTtsProvider._auto_device(fake_torch(False, False)) == "cpu"


def test_load_kwargs_use_cuda_bfloat16():
    import types

    fake_torch = types.SimpleNamespace(bfloat16="bf16", float32="fp32")

    assert QwenTtsProvider._load_kwargs(fake_torch, "cuda:0") == {
        "device_map": "cuda:0",
        "dtype": "bf16",
    }


def test_load_kwargs_use_sdpa_float32_for_mps():
    fake_torch = types.SimpleNamespace(bfloat16="bf16", float32="fp32")

    assert QwenTtsProvider._load_kwargs(fake_torch, "mps") == {
        "device_map": "mps",
        "dtype": "fp32",
        "attn_implementation": "sdpa",
    }


def test_load_model_uses_yumi_cache_dir(monkeypatch, tmp_path):
    from yumi.core.features.tts import qwen_provider

    captured = {}

    class FakeQwenModel:
        @classmethod
        def from_pretrained(cls, model_name, **kwargs):
            captured.update(model_name=model_name, kwargs=kwargs)
            return "loaded-model"

    fake_torch = types.SimpleNamespace(
        cuda=types.SimpleNamespace(is_available=lambda: False),
        backends=types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: False)),
        bfloat16="bf16",
        float32="fp32",
    )
    fake_qwen_tts = types.ModuleType("qwen_tts")
    fake_qwen_tts.Qwen3TTSModel = FakeQwenModel
    cache_dir = tmp_path / "qwen-tts"
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "qwen_tts", fake_qwen_tts)
    monkeypatch.setattr(qwen_provider, "QWEN_TTS_MODELS_DIR", cache_dir)

    provider = QwenTtsProvider(device="cpu")

    assert provider._load_model() == "loaded-model"
    assert captured["model_name"] == "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
    assert captured["kwargs"]["cache_dir"] == str(cache_dir)
    assert captured["kwargs"]["device_map"] == "cpu"
    assert cache_dir.exists()


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
