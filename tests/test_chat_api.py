"""Focused HTTP tests for the local /chat endpoint."""

import json

import kumi.core.api.routers.chat as chat_router_module
from fastapi.testclient import TestClient
from kumi.core.api.app_factory import app


def test_chat_endpoint_streams_ndjson(monkeypatch):
    async def fake_generate_chat_events(prompt: str, session_id: str, think: bool = False):
        assert prompt == "Hello"
        assert session_id == "s1"
        assert think is True
        yield {"type": "text", "content": "Hi there"}
        yield {"type": "tool_status", "status": "success", "content": "timer finished"}

    monkeypatch.setattr(chat_router_module, "generate_chat_events", fake_generate_chat_events)

    client = TestClient(app)
    response = client.post("/chat", json={"prompt": "Hello", "session_id": "s1", "think": True})

    assert response.status_code == 200
    assert "application/x-ndjson" in response.headers["content-type"]

    lines = [json.loads(line) for line in response.text.splitlines()]
    assert lines == [
        {"type": "text", "content": "Hi there"},
        {"type": "tool_status", "status": "success", "content": "timer finished"},
    ]
