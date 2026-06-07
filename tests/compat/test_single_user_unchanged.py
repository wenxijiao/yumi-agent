"""Regression: default single-user mode stays usable without Bearer tokens."""

import kumi.core.features.chat.router as chat_router_module
from fastapi.testclient import TestClient
from kumi.core.api.app_factory import app


def test_chat_post_works_without_bearer_single_user_mode(monkeypatch):
    async def fake_gen(prompt: str, session_id: str, think: bool = False):
        yield {"type": "text", "content": "x"}

    monkeypatch.setattr(chat_router_module, "generate_chat_events", fake_gen)

    client = TestClient(app)
    r = client.post("/chat", json={"prompt": "hi", "session_id": "default"})
    assert r.status_code == 200
