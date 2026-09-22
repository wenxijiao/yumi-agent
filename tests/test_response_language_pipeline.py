"""Language settings reach the current request without rewriting saved chat."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace as NS

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from yumi.core.chatbot import YumiBot
from yumi.core.features.assistant import router
from yumi.core.features.assistant.personalization import preferences, save_preferences
from yumi.core.features.chat.language import language_scoped_prompt
from yumi.core.features.chat.service import ChatTurnService
from yumi.core.features.config.model import ModelConfig
from yumi.core.features.prompts.composer import compose_messages
from yumi.core.platform.http.dependencies import current_identity_dependency
from yumi.core.platform.plugins.identity import Identity
from yumi.core.platform.providers.base import BaseLLMProvider
from yumi.core.platform.runtime import RuntimeState
from yumi.core.platform.runtime.assistant_context import PromptSnapshot
from yumi.core.platform.storage.assistant_store import AssistantStore
from yumi.core.platform.storage.sqlite_store import SQLiteStore
from yumi.core.platform.tools.replay import normalize_tool_history


class CapturingProvider(BaseLLMProvider):
    def __init__(self):
        self.requests = []

    async def chat_stream(self, model, messages, **kwargs):
        self.requests.append(deepcopy(messages))
        yield {"type": "text", "content": "A test reply"}


class MemoryStub:
    session_id = "u_alice__personal_language"

    def __init__(self):
        self.saved = []
        self.history = [
            {"role": "system", "content": "You are Yumi."},
            {"role": "user", "content": "こんにちは"},
            {"role": "assistant", "content": "こんにちは！"},
        ]

    def get_context(self, **kwargs):
        return deepcopy(self.history)

    def add_message(self, role, content, **kwargs):
        self.saved.append({"role": role, "content": content})
        return str(len(self.saved))

    def persist_openai_messages(self, messages):
        self.saved.extend(deepcopy(messages))


def test_api_language_change_reaches_next_model_request_and_keeps_raw_history(tmp_path, monkeypatch):
    from yumi.core.features.chat import service
    from yumi.core.platform.runtime import assistant_context

    sqlite = SQLiteStore(tmp_path / "language.db")
    alice, bob = AssistantStore(sqlite, "alice"), AssistantStore(sqlite, "bob")
    memory = MemoryStub()
    alice.put("state", {"session_id": memory.session_id, "revision": 1})
    save_preferences(bob, response_language="ja")
    provider = CapturingProvider()
    bot = YumiBot(provider, "test", runtime_config=ModelConfig(chat_append_current_time=False))
    monkeypatch.setattr(bot, "_get_memory", lambda sid: memory)
    monkeypatch.setattr(router, "_store", lambda _: alice)
    monkeypatch.setattr(assistant_context, "personal_store", lambda uid: alice if uid == "alice" else bob)
    monkeypatch.setattr(service, "get_session_scope", lambda: NS(owner_user_from_session_id=lambda _: "alice"))

    async def get_bot(owner):
        assert owner == "alice"
        return bot

    async def no_context():
        return None

    monkeypatch.setattr(service, "get_bot_pool", lambda: NS(get_bot_for_session_owner=get_bot))
    monkeypatch.setattr(service, "runtime_context_prompt_block", no_context)
    monkeypatch.setattr(service, "select_tool_schemas", lambda **kwargs: NS(tools=None))
    monkeypatch.setattr("yumi.core.features.memory.index_queue.start_worker", lambda _: None)
    monkeypatch.setattr("yumi.core.features.memory.compaction.schedule_compaction", lambda _: None)
    app = FastAPI()
    app.include_router(router.router)
    app.dependency_overrides[current_identity_dependency] = lambda: Identity(user_id="alice")
    prompt = "じゃあ、おやすみ。"

    async def send():
        return [e async for e in ChatTurnService(RuntimeState()).stream_chat_turn(prompt, memory.session_id)]

    with TestClient(app) as client:
        for language in ("ja", "zh", "en", "auto", "Māori"):
            assert client.put("/assistant/preferences", json={"response_language": language}).status_code == 200
            events = asyncio.run(send())
            assert any(getattr(e, "type", None) == "text" for e in events), events
            current = [m for m in provider.requests[-1] if m["role"] == "user"][-1]
            assert current["content"] == language_scoped_prompt(prompt, language)
            assert provider.requests[-1][1:3] == memory.history[1:3]
    assert [m["content"] for m in memory.saved if m["role"] == "user"] == [prompt] * 5
    assert preferences(bob)["response_language"] == "ja"


def test_tool_round_keeps_current_language_and_call_ids_without_an_extra_user_turn():
    memory = MemoryStub()
    original = deepcopy(memory.history)
    snapshot = PromptSnapshot()
    cfg = ModelConfig(chat_append_current_time=False)
    first = compose_messages(
        memory,
        prompt="Tell me the weather",
        tools=None,
        ephemeral_messages=[],
        cfg=cfg,
        upload_mode="vision",
        prompt_snapshot=snapshot,
        response_language="zh",
    )
    snapshot.tool_messages = [
        {
            "role": "assistant",
            "tool_calls": [{"id": "weather-1", "type": "function", "function": {"name": "weather", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "weather-1", "content": "今日は雨です"},
    ]
    second = compose_messages(
        memory,
        prompt=None,
        tools=None,
        ephemeral_messages=[],
        cfg=cfg,
        upload_mode="vision",
        prompt_snapshot=snapshot,
        response_language="zh",
    )
    assert second[: len(first)] == first  # Keep the provider cache prefix.
    assert second[-1]["tool_call_id"] == "weather-1"
    assert normalize_tool_history(second, strict=True) == second
    assert sum(m["role"] == "user" for m in second) == 2
    assert '"Chinese"' in [m for m in second if m["role"] == "user"][-1]["content"]
    assert memory.history == original


@pytest.mark.parametrize("mode", ["vision", "no_vision"])
def test_upload_and_explicit_translation_request_are_preserved(mode, monkeypatch):
    from yumi.core.features.prompts import composer

    seen = []
    monkeypatch.setattr(
        composer, "_inline_uploaded_images", lambda messages, **kwargs: seen.extend(deepcopy(messages)) or messages
    )
    prompt = "Please translate into French. Image: /tmp/.yumi/uploads/picture.jpg"
    compose_messages(
        MemoryStub(),
        prompt=prompt,
        tools=None,
        ephemeral_messages=[],
        cfg=ModelConfig(chat_append_current_time=False),
        upload_mode=mode,
        response_language="en",
    )
    assert prompt in seen[-1]["content"]
    assert "translation takes priority" in seen[-1]["content"]
    assert '"English"' in seen[-1]["content"]
