from __future__ import annotations

import asyncio

from yumi.core.features.chat import router as chat_router
from yumi.core.platform.http.schemas import ChatRequest
from yumi.core.platform.plugins import LOCAL_IDENTITY


class _Quota:
    def __init__(self) -> None:
        self.records = 0

    def check_chat_allowed(self, identity):  # noqa: ARG002
        return True, ""

    def check_token_quota(self, identity):  # noqa: ARG002
        return True, ""

    def record_chat_turn(self, identity):  # noqa: ARG002
        self.records += 1
        return self.records


class _SessionScope:
    def qualify_session_http(self, identity, client_session_id):  # noqa: ARG002
        return f"u:{identity.user_id}:{client_session_id}"


async def _consume_response(resp) -> str:
    chunks = []
    async for chunk in resp.body_iterator:
        chunks.append(chunk)
    return "".join(chunks)


def test_chat_quota_not_recorded_when_stream_only_errors(monkeypatch):
    quota = _Quota()
    monkeypatch.setattr(chat_router, "get_quota_policy", lambda: quota)
    monkeypatch.setattr(chat_router, "get_session_scope", lambda: _SessionScope())
    monkeypatch.setattr(chat_router, "audit_event", lambda *args, **kwargs: None)

    async def _fake_events(prompt, sid, think=False):  # noqa: ARG001
        yield {"type": "error", "content": "provider failed"}

    monkeypatch.setattr(chat_router, "generate_chat_events", _fake_events)

    resp = asyncio.run(chat_router.chat_endpoint(object(), LOCAL_IDENTITY, ChatRequest(prompt="hi")))
    body = asyncio.run(_consume_response(resp))

    assert "provider failed" in body
    assert quota.records == 0


def test_chat_quota_recorded_once_after_first_non_error_event(monkeypatch):
    quota = _Quota()
    monkeypatch.setattr(chat_router, "get_quota_policy", lambda: quota)
    monkeypatch.setattr(chat_router, "get_session_scope", lambda: _SessionScope())
    monkeypatch.setattr(chat_router, "audit_event", lambda *args, **kwargs: None)

    async def _fake_events(prompt, sid, think=False):  # noqa: ARG001
        yield {"type": "text", "content": "hello"}
        yield {"type": "text", "content": " world"}

    monkeypatch.setattr(chat_router, "generate_chat_events", _fake_events)

    resp = asyncio.run(chat_router.chat_endpoint(object(), LOCAL_IDENTITY, ChatRequest(prompt="hi")))
    body = asyncio.run(_consume_response(resp))

    assert "hello" in body
    assert quota.records == 1
