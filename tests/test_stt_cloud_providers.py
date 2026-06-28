from __future__ import annotations

import asyncio

import pytest
from yumi.core.features.config.model import ModelConfig
from yumi.core.features.stt import create_stt_provider
from yumi.core.features.stt.base import SttError
from yumi.core.features.stt.grok_provider import GrokSttProvider
from yumi.core.features.stt.openai_provider import OpenAiSttProvider


def test_factory_builds_openai_stt():
    provider = create_stt_provider(ModelConfig(stt_provider="openai", stt_model="gpt-4o-transcribe"))

    assert isinstance(provider, OpenAiSttProvider)


def test_factory_builds_grok_stt():
    provider = create_stt_provider(ModelConfig(stt_provider="grok", grok_api_key="xai"))

    assert isinstance(provider, GrokSttProvider)


def test_grok_stt_posts_audio(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"text": "hello grok", "language": "en", "duration": 2.0}

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

    monkeypatch.setattr("yumi.core.features.stt.grok_provider.httpx.AsyncClient", FakeAsyncClient)

    provider = GrokSttProvider(api_key="xai", base_url="https://api.x.ai/v1")
    result = asyncio.run(provider.transcribe(b"audio", filename="recording.mp3", language="zh"))

    assert result.text == "hello grok"
    assert calls[0][0] == "https://api.x.ai/v1/stt"
    assert calls[0][1]["headers"]["Authorization"] == "Bearer xai"
    assert calls[0][1]["files"]["file"][0] == "recording.mp3"
    assert calls[0][1]["files"]["file"][1] == b"audio"


def test_grok_stt_error_status_raises(monkeypatch):
    class FakeResponse:
        status_code = 401
        text = "nope"

        def json(self):
            return {"error": "nope"}

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, *_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr("yumi.core.features.stt.grok_provider.httpx.AsyncClient", FakeAsyncClient)

    provider = GrokSttProvider(api_key="xai")
    with pytest.raises(SttError, match="Grok STT failed"):
        asyncio.run(provider.transcribe(b"audio", filename="voice.wav"))
