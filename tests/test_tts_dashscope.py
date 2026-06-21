"""DashScope (Qwen3-TTS API) provider — PCM accumulation + factory wiring.

The SDK call is mocked via the `_stream_chunks` seam, so no network or
`dashscope` package is needed to run these.
"""

import asyncio
import base64
import io
import types
import wave

import pytest
from yumi.core.features.config.model import ModelConfig
from yumi.core.features.tts import create_tts_provider
from yumi.core.features.tts.base import TtsError
from yumi.core.features.tts.dashscope_provider import DashScopeTtsProvider


def _chunk(b64: str | None):
    """A stand-in for a DashScope streaming chunk: chunk.output.audio.data."""
    audio = types.SimpleNamespace(data=b64)
    return types.SimpleNamespace(output=types.SimpleNamespace(audio=audio))


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    with pytest.raises(TtsError):
        DashScopeTtsProvider(api_key=None)


def test_factory_builds_dashscope_from_config(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    provider = create_tts_provider(ModelConfig(tts_provider="dashscope", tts_voice="Cherry"))
    assert isinstance(provider, DashScopeTtsProvider)


def test_chunk_audio_b64_parsing():
    assert DashScopeTtsProvider._chunk_audio_b64(_chunk("AAA=")) == "AAA="
    assert DashScopeTtsProvider._chunk_audio_b64(_chunk(None)) is None
    assert DashScopeTtsProvider._chunk_audio_b64(types.SimpleNamespace(output=None)) is None


def test_synthesize_accumulates_pcm_into_wav(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    provider = DashScopeTtsProvider()
    pcm_a = b"\x01\x02" * 10
    pcm_b = b"\x03\x04" * 10
    chunks = [
        _chunk(base64.b64encode(pcm_a).decode()),
        _chunk(None),  # a metadata-only chunk with no audio
        _chunk(base64.b64encode(pcm_b).decode()),
    ]
    monkeypatch.setattr(provider, "_stream_chunks", lambda text, voice, language: iter(chunks))

    audio = asyncio.run(provider.synthesize("hello", voice="Cherry"))
    assert audio.format == "wav"
    assert audio.sample_rate == 24000
    with wave.open(io.BytesIO(audio.data), "rb") as w:
        assert (w.getframerate(), w.getnchannels(), w.getsampwidth()) == (24000, 1, 2)
        frames = w.readframes(w.getnframes())
    assert frames == pcm_a + pcm_b  # segments concatenated in order


def test_synthesize_without_audio_raises(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    provider = DashScopeTtsProvider()
    monkeypatch.setattr(provider, "_stream_chunks", lambda text, voice, language: iter([_chunk(None)]))
    with pytest.raises(TtsError):
        asyncio.run(provider.synthesize("hello"))
