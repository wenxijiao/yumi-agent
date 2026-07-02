"""In-core LINE webhook (OSS single-user): signature + empty events + happy text."""

import asyncio
import base64
import hashlib
import hmac
import json

import pytest
import yumi.core.api.app_factory as api
from fastapi.testclient import TestClient
from yumi.core.features.config.model import ModelConfig
from yumi.line.client import LineMessagingClient


@pytest.fixture(autouse=True)
def _line_tests_stub_chat_model_config(monkeypatch):
    """``lifespan`` calls ``ensure_chat_model_configured``; stub so tests do not depend on env / ~/.yumi.

    CI may set ``YUMI_CHAT_MODEL`` to an empty value or merge config in an order that still leaves
    ``chat_model`` unset; patching the function used by ``routes.lifespan`` is reliable.
    """

    def _ensure(*, interactive: bool = False) -> ModelConfig:
        return ModelConfig(chat_model="test-dummy-model")

    monkeypatch.setattr("yumi.core.api.app_factory.ensure_chat_model_configured", _ensure)


def _sign(body: bytes, secret: str) -> str:
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    return base64.b64encode(mac).decode("ascii")


def test_line_webhook_bad_signature(monkeypatch):
    monkeypatch.setenv("YUMI_LINE_INCORE", "1")
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "sec")
    body = b'{"events":[]}'
    with TestClient(api.app) as client:
        r = client.post("/line/webhook", content=body, headers={"X-Line-Signature": "bad"})
    assert r.status_code == 401


def test_line_webhook_ok_empty_events(monkeypatch):
    monkeypatch.setenv("YUMI_LINE_INCORE", "1")
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "sec")
    body = b'{"events":[]}'
    sig = _sign(body, "sec")
    with TestClient(api.app) as client:
        r = client.post("/line/webhook", content=body, headers={"X-Line-Signature": sig})
    assert r.status_code == 200


async def _noop_coro(*_a, **_k):
    return None


async def _stream_one_text(*_a, **_k):
    yield {"type": "text", "content": "ok"}


async def _drain_line_pending_tasks():
    for _ in range(10):
        tasks = set(getattr(api.app.state, "line_pending_tasks", set()) or ())
        if not tasks:
            return
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.sleep(0)


def test_line_webhook_text_message_single_user(monkeypatch):
    """Signed text event in single-user mode → 200 (chat stream mocked)."""
    monkeypatch.setenv("YUMI_LINE_INCORE", "1")
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "sec")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "token")

    monkeypatch.setattr("yumi.line.handlers.stream_line_chat", _stream_one_text)
    monkeypatch.setattr(LineMessagingClient, "reply_message", _noop_coro)
    monkeypatch.setattr(LineMessagingClient, "push_message", _noop_coro)

    payload = {
        "events": [
            {
                "type": "message",
                "replyToken": "dummy-reply-token",
                "source": {"type": "user", "userId": "Uoss1"},
                "message": {"type": "text", "id": "mid1", "text": "hello"},
            }
        ]
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = _sign(body, "sec")
    with TestClient(api.app) as client:
        r = client.post("/line/webhook", content=body, headers={"X-Line-Signature": sig})
        client.portal.call(_drain_line_pending_tasks)
    assert r.status_code == 200


def test_line_webhook_audio_message_transcribes_single_user(monkeypatch):
    """Signed audio event in single-user mode → STT text is passed to chat."""
    monkeypatch.setenv("YUMI_LINE_INCORE", "1")
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "sec")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "token")

    seen: list[str] = []

    async def _fake_transcribe(audio: bytes, *, filename: str, language: str | None = None):
        from yumi.core.features.stt import TranscriptionResult

        assert audio == b"voice-bytes"
        assert filename == "line_audio_mid-audio.m4a"
        assert language is None
        return TranscriptionResult(text="transcribed text")

    async def _stream_capture(_line_user_id, prompt, _session_id, *, use_http):
        seen.append(prompt)
        yield {"type": "text", "content": "ok"}

    async def _content(self, message_id: str):
        assert message_id == "mid-audio"
        return b"voice-bytes"

    monkeypatch.setattr("yumi.core.features.stt.transcribe_audio", _fake_transcribe)
    monkeypatch.setattr("yumi.line.handlers.stream_line_chat", _stream_capture)
    monkeypatch.setattr(LineMessagingClient, "get_message_content", _content)
    monkeypatch.setattr(LineMessagingClient, "reply_message", _noop_coro)
    monkeypatch.setattr(LineMessagingClient, "push_message", _noop_coro)
    monkeypatch.setattr(LineMessagingClient, "show_loading_animation", _noop_coro)

    payload = {
        "events": [
            {
                "type": "message",
                "replyToken": "dummy-reply-token",
                "source": {"type": "user", "userId": "Uoss1"},
                "message": {"type": "audio", "id": "mid-audio", "duration": 1000},
            }
        ]
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    sig = _sign(body, "sec")
    with TestClient(api.app) as client:
        r = client.post("/line/webhook", content=body, headers={"X-Line-Signature": sig})
        client.portal.call(_drain_line_pending_tasks)
    assert r.status_code == 200
    assert seen == ["transcribed text"]
