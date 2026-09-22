import io
import wave
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from yumi.core.platform.plugins import LOCAL_IDENTITY, usage_guard


def wav(seconds=1):
    out = io.BytesIO()
    with wave.open(out, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(8000)
        f.writeframes(b"\0" * (seconds * 16000))
    return out.getvalue()


def test_optional_hooks_preserve_older_plugins(monkeypatch):
    monkeypatch.setattr(usage_guard, "get_quota_policy", lambda: object())
    with usage_guard.chat_turn_scope(LOCAL_IDENTITY):
        usage_guard.reserve_speech(LOCAL_IDENTITY, audio=b"older-provider-format")


def test_speech_reserves_measured_duration_and_characters(monkeypatch):
    calls = []
    monkeypatch.setattr(
        usage_guard, "get_quota_policy", lambda: SimpleNamespace(reserve_voice=lambda identity, **kw: calls.append(kw))
    )
    usage_guard.reserve_speech(LOCAL_IDENTITY, audio=wav(2))
    usage_guard.reserve_speech(LOCAL_IDENTITY, text="Hello 你好")
    assert calls == [{"kind": "voice_seconds", "units": 2}, {"kind": "speech_characters", "units": 8}]
    with pytest.raises(HTTPException):
        usage_guard.reserve_speech(LOCAL_IDENTITY, audio=wav(66))
    assert len(calls) == 2


@pytest.mark.anyio
async def test_pipeline_holds_admission_through_model_work(monkeypatch):
    from yumi.core.features.chat import pipeline
    from yumi.core.platform.http.events import TextEvent

    state = {"held": False, "calls": 0}

    @contextmanager
    def scope(identity):
        state["held"] = True
        try:
            yield
        finally:
            state["held"] = False

    class Service:
        async def stream_chat_turn(self, *args, **kw):
            assert state["held"]
            state["calls"] += 1
            yield TextEvent(content="Hello")

    monkeypatch.setattr(usage_guard, "get_quota_policy", lambda: SimpleNamespace(chat_turn=scope))
    monkeypatch.setattr(pipeline, "ChatTurnService", Service)
    events = [e async for e in pipeline.stream_chat_events("Hi", "default")]
    assert len(events) == 1 and state == {"held": False, "calls": 1}


@pytest.mark.anyio
async def test_pipeline_denied_admission_never_calls_model(monkeypatch):
    from yumi.core.features.chat import pipeline

    @contextmanager
    def scope(identity):
        raise HTTPException(429, "Demo ended")
        yield

    monkeypatch.setattr(usage_guard, "get_quota_policy", lambda: SimpleNamespace(chat_turn=scope))
    monkeypatch.setattr(pipeline, "ChatTurnService", lambda: pytest.fail("Model invoked before quota check"))
    with pytest.raises(HTTPException) as exc:
        async for _ in pipeline.stream_chat_events("Hi", "default"):
            pass
    assert exc.value.status_code == 429


@pytest.fixture
def anyio_backend():
    return "asyncio"
