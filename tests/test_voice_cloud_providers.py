"""Cloud STT/TTS provider contract tests with each SDK mocked out."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

from yumi.core.features.config.model import ModelConfig

# ── factory wiring ───────────────────────────────────────────────────────────


def test_factory_returns_gemini_stt():
    from yumi.core.features.stt.factory import create_stt_provider
    from yumi.core.features.stt.gemini_provider import GeminiSttProvider

    provider = create_stt_provider(ModelConfig(stt_provider="gemini", stt_model="gemini-2.5-flash"))
    assert isinstance(provider, GeminiSttProvider)


def test_factory_returns_dashscope_stt():
    from yumi.core.features.stt.dashscope_provider import DashScopeSttProvider
    from yumi.core.features.stt.factory import create_stt_provider

    provider = create_stt_provider(
        ModelConfig(stt_provider="dashscope", stt_model="qwen3-asr-flash", tts_api_key="ds-key")
    )
    assert isinstance(provider, DashScopeSttProvider)


def test_factory_returns_openai_tts():
    from yumi.core.features.tts.factory import create_tts_provider
    from yumi.core.features.tts.openai_provider import OpenAiTtsProvider

    provider = create_tts_provider(ModelConfig(tts_provider="openai", tts_voice="nova"))
    assert isinstance(provider, OpenAiTtsProvider)


# ── transcription / synthesis ────────────────────────────────────────────────


def test_gemini_stt_transcribes(monkeypatch):
    from yumi.core.features.stt.gemini_provider import GeminiSttProvider

    captured: dict = {}

    class _FakeModels:
        def generate_content(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(text="  bonjour  ")

    class _FakeClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            self.models = _FakeModels()

    class _Part:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class _Blob:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    fake_genai = SimpleNamespace(Client=_FakeClient, types=SimpleNamespace(Part=_Part, Blob=_Blob))
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google", SimpleNamespace(genai=fake_genai))
    monkeypatch.setattr(
        "yumi.core.features.config.credentials.get_api_credentials",
        lambda: {"gemini_api_key": "g-test"},
    )

    provider = GeminiSttProvider(model="gemini-2.5-flash", language="fr")
    # The real voice loop hands Gemini a ".wav" file — exactly the suffix whose
    # mimetypes.guess_type() (audio/x-wav) Gemini would reject.
    result = asyncio.run(provider.transcribe(b"audio-bytes", filename="voice.wav", language=None))

    assert result.text == "bonjour"
    assert result.language == "fr"
    assert captured["model"] == "gemini-2.5-flash"
    assert captured["client_kwargs"]["api_key"] == "g-test"
    assert len(captured["contents"]) == 2  # audio blob + prompt
    blob = captured["contents"][0].kwargs["inline_data"]
    assert blob.kwargs["mime_type"] == "audio/wav"  # canonical, not audio/x-wav


def test_gemini_audio_mime_is_canonical():
    """_guess_audio_mime must return Gemini's accepted MIME strings, not the
    platform-specific ones mimetypes.guess_type() produces (audio/x-wav etc.)."""
    from yumi.core.features.stt.gemini_provider import _GEMINI_ACCEPTED_MIME, _guess_audio_mime

    assert _guess_audio_mime("voice.wav") == "audio/wav"
    assert _guess_audio_mime("clip.mp3") == "audio/mp3"
    assert _guess_audio_mime("line_audio_42.m4a") == "audio/aac"
    assert _guess_audio_mime("x.aac") == "audio/aac"
    assert _guess_audio_mime("x.flac") == "audio/flac"
    assert _guess_audio_mime("x.ogg") == "audio/ogg"
    # Unknown suffix falls back to a Gemini-accepted default.
    assert _guess_audio_mime("mystery.bin") in _GEMINI_ACCEPTED_MIME


def test_openai_stt_uses_configured_base_url(monkeypatch):
    """OpenAI STT must honor openai_base_url (proxy / Azure) like the chat path,
    so a user on a custom endpoint isn't silently routed to api.openai.com."""
    from yumi.core.features.stt.openai_provider import OpenAiSttProvider

    captured: dict = {}

    class _FakeTranscriptions:
        async def create(self, **kwargs):
            return SimpleNamespace(text="ok")

    class _FakeClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            self.audio = SimpleNamespace(transcriptions=_FakeTranscriptions())

        async def close(self):
            pass

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(AsyncOpenAI=_FakeClient))
    monkeypatch.setattr(
        "yumi.core.features.config.credentials.get_api_credentials",
        lambda: {"openai_api_key": "sk-test", "openai_base_url": "https://proxy.example/v1"},
    )

    provider = OpenAiSttProvider(model="whisper-1")
    asyncio.run(provider.transcribe(b"audio-bytes", filename="voice.wav", language=None))

    assert captured["client_kwargs"]["base_url"] == "https://proxy.example/v1"


def test_dashscope_stt_transcribes(monkeypatch):
    from yumi.core.features.stt.dashscope_provider import DashScopeSttProvider

    captured: dict = {}

    class _FakeMMC:
        @staticmethod
        def call(**kwargs):
            captured.update(kwargs)
            message = SimpleNamespace(content=[{"text": "hola"}])
            return SimpleNamespace(status_code=200, output=SimpleNamespace(choices=[SimpleNamespace(message=message)]))

    monkeypatch.setitem(
        sys.modules, "dashscope", SimpleNamespace(MultiModalConversation=_FakeMMC, base_http_api_url="")
    )

    provider = DashScopeSttProvider(model="qwen3-asr-flash", api_key="ds-key")
    result = asyncio.run(provider.transcribe(b"audio-bytes", filename="voice.wav", language=None))

    assert result.text == "hola"
    assert captured["model"] == "qwen3-asr-flash"
    assert captured["api_key"] == "ds-key"
    audio_ref = captured["messages"][0]["content"][0]["audio"]
    assert audio_ref.startswith("file://")


def test_openai_tts_synthesizes(monkeypatch):
    from yumi.core.features.tts.openai_provider import OpenAiTtsProvider

    captured: dict = {}

    class _FakeSpeech:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(content=b"WAVDATA")

    class _FakeClient:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs
            self.audio = SimpleNamespace(speech=_FakeSpeech())

        async def close(self):
            captured["closed"] = True

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(AsyncOpenAI=_FakeClient))
    monkeypatch.setattr(
        "yumi.core.features.config.credentials.get_api_credentials",
        lambda: {"openai_api_key": "sk-test"},
    )

    provider = OpenAiTtsProvider(model="gpt-4o-mini-tts", voice="nova")
    audio = asyncio.run(provider.synthesize("hello", voice=None, language=None))

    assert audio.data == b"WAVDATA"
    # WAV (not mp3) so it plays through the WAV-only local backends (winsound/aplay).
    assert audio.format == "wav"
    assert captured["response_format"] == "wav"
    assert audio.voice == "nova"
    assert captured["model"] == "gpt-4o-mini-tts"
    assert captured["voice"] == "nova"
    assert captured["input"] == "hello"
    assert captured.get("closed") is True
