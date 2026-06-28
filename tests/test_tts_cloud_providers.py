from __future__ import annotations

import asyncio
import io
import sys
import wave
from types import SimpleNamespace

import pytest
from yumi.core.features.config.model import ModelConfig
from yumi.core.features.tts import create_tts_provider
from yumi.core.features.tts.base import TtsError
from yumi.core.features.tts.gemini_provider import GeminiTtsProvider
from yumi.core.features.tts.grok_provider import GrokTtsProvider
from yumi.core.features.tts.openai_provider import OpenAiTtsProvider


def test_factory_builds_cloud_tts_providers(monkeypatch):
    fake_genai = SimpleNamespace(Client=lambda **_kwargs: object())
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(genai=fake_genai))
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)

    openai_provider = create_tts_provider(ModelConfig(tts_provider="openai", openai_api_key="sk"))
    grok_provider = create_tts_provider(ModelConfig(tts_provider="grok", grok_api_key="xai"))
    gemini_provider = create_tts_provider(ModelConfig(tts_provider="gemini", gemini_api_key="gem"))

    assert isinstance(openai_provider, OpenAiTtsProvider)
    assert isinstance(grok_provider, GrokTtsProvider)
    assert isinstance(gemini_provider, GeminiTtsProvider)


def test_openai_tts_synthesizes_wav(monkeypatch):
    calls = []

    class FakeSpeech:
        async def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(content=b"RIFFwav")

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.audio = SimpleNamespace(speech=FakeSpeech())

        async def close(self):
            pass

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(AsyncOpenAI=FakeAsyncOpenAI))
    monkeypatch.setattr(
        "yumi.core.features.config.credentials.get_api_credentials",
        lambda: {"openai_api_key": "sk"},
    )

    provider = OpenAiTtsProvider(model="gpt-4o-mini-tts", voice="coral")
    audio = asyncio.run(provider.synthesize("hello", voice="cedar", language="zh"))

    assert audio.data == b"RIFFwav"
    assert audio.format == "wav"
    assert audio.voice == "cedar"
    assert calls[0] == {
        "model": "gpt-4o-mini-tts",
        "voice": "cedar",
        "input": "hello",
        "response_format": "wav",
    }


def test_grok_tts_posts_json(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 200
        content = b"MP3"

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return FakeResponse()

    monkeypatch.setattr("yumi.core.features.tts.grok_provider.httpx.AsyncClient", FakeAsyncClient)

    provider = GrokTtsProvider(api_key="xai", base_url="https://api.x.ai/v1", voice="eve", language="auto")
    audio = asyncio.run(provider.synthesize("hello", voice="ara"))

    assert audio.data == b"MP3"
    assert audio.format == "mp3"
    assert audio.voice == "ara"
    assert calls[0][0] == "https://api.x.ai/v1/tts"
    assert calls[0][1]["json"] == {"text": "hello", "voice_id": "ara", "language": "en"}


def test_gemini_tts_wraps_pcm_in_wav(monkeypatch):
    pcm = b"\x00\x00\x01\x00" * 4
    fake_models = None

    class FakePrebuiltVoiceConfig:
        def __init__(self, *, voice_name):
            self.voice_name = voice_name

    class FakeVoiceConfig:
        def __init__(self, *, prebuilt_voice_config):
            self.prebuilt_voice_config = prebuilt_voice_config

    class FakeSpeechConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeGenerateContentConfig:
        def __init__(self, *, response_modalities, speech_config):
            self.response_modalities = response_modalities
            self.speech_config = speech_config

    class FakeModels:
        def generate_content(self, **kwargs):
            self.kwargs = kwargs
            inline = SimpleNamespace(data=pcm)
            part = SimpleNamespace(inline_data=inline)
            content = SimpleNamespace(parts=[part])
            return SimpleNamespace(candidates=[SimpleNamespace(content=content)])

    class FakeClient:
        def __init__(self, **_kwargs):
            nonlocal fake_models
            fake_models = FakeModels()
            self.models = fake_models

    fake_types = SimpleNamespace(
        GenerateContentConfig=FakeGenerateContentConfig,
        SpeechConfig=FakeSpeechConfig,
        VoiceConfig=FakeVoiceConfig,
        PrebuiltVoiceConfig=FakePrebuiltVoiceConfig,
    )
    fake_genai = SimpleNamespace(Client=FakeClient, types=fake_types)
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(genai=fake_genai))
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)

    provider = GeminiTtsProvider(api_key="gem", model="gemini-3.1-flash-tts-preview", voice="Kore")
    audio = asyncio.run(provider.synthesize("hello", voice="Puck", language="ja"))

    assert audio.format == "wav"
    assert audio.sample_rate == 24000
    assert audio.voice == "Puck"
    with wave.open(io.BytesIO(audio.data), "rb") as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (24000, 1, 2)
        assert wav.readframes(wav.getnframes()) == pcm
    assert fake_models is not None
    config = fake_models.kwargs["config"]
    assert config.response_modalities == ["AUDIO"]
    assert config.speech_config.voice_config.prebuilt_voice_config.voice_name == "Puck"
    assert config.speech_config.language_code == "ja"


def test_grok_tts_error_status_raises(monkeypatch):
    class FakeResponse:
        status_code = 500
        content = b""
        text = "bad"

        def json(self):
            return {"error": "bad"}

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr("yumi.core.features.tts.grok_provider.httpx.AsyncClient", FakeAsyncClient)

    provider = GrokTtsProvider(api_key="xai")
    with pytest.raises(TtsError, match="Grok TTS failed"):
        asyncio.run(provider.synthesize("hello"))
