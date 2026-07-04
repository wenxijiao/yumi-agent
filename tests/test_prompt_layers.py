from __future__ import annotations

import asyncio
import tempfile

from yumi.core.features.config.model import ModelConfig
from yumi.core.features.memory.memory import Memory
from yumi.core.features.prompts.composer import compose_messages
from yumi.core.platform.tools.context_prefetch import runtime_context_prompt_block
from yumi.core.platform.tools.tool import TOOL_REGISTRY, register_tool


def test_stable_user_context_is_included_as_own_system_layer():
    with tempfile.TemporaryDirectory() as td:
        memory = Memory(session_id="s_stable_context", storage_dir=td, max_recent=20)
        memory.create_long_term_memory(
            kind="preference",
            content="The user prefers concise deployment checklists.",
            session_id="s_stable_context",
            importance=0.9,
        )

        ctx = memory.get_context(query="How should we deploy?")
        stable = [
            msg
            for msg in ctx
            if msg["role"] == "system" and msg["content"].startswith("Stable User Context:")
        ]

        assert stable
        assert "durable memories" in stable[0]["content"]
        assert "concise deployment checklists" in stable[0]["content"]


def test_runtime_context_prompt_block_groups_local_autorun_context():
    previous = dict(TOOL_REGISTRY)
    TOOL_REGISTRY.clear()

    def room_status() -> str:
        return "room=office; light=warm"

    try:
        register_tool(
            room_status,
            "Current room status",
            proactive_context=True,
            proactive_context_description="Room status",
        )

        block = asyncio.run(runtime_context_prompt_block())

        assert block is not None
        assert "[Turn Runtime Context]" in block
        assert "## Local Autorun Context" in block
        assert "- Room status (room_status): room=office; light=warm" in block
    finally:
        TOOL_REGISTRY.clear()
        TOOL_REGISTRY.update(previous)


def test_runtime_context_system_note_is_placed_before_user_history():
    with tempfile.TemporaryDirectory() as td:
        memory = Memory(session_id="s_runtime_order", storage_dir=td, max_recent=20)
        memory.add_message("user", "hello")

        messages = compose_messages(
            memory,
            prompt="hello",
            tools=None,
            ephemeral_messages=[{"role": "system", "content": "[Turn Runtime Context]\nroom=office"}],
            cfg=ModelConfig(),
            upload_mode="vision",
        )

        runtime_idx = next(i for i, msg in enumerate(messages) if msg.get("content", "").startswith("[Turn Runtime"))
        user_idx = next(i for i, msg in enumerate(messages) if msg.get("role") == "user")
        assert runtime_idx < user_idx


def test_current_prompt_is_final_user_layer_not_recent_history_duplicate():
    with tempfile.TemporaryDirectory() as td:
        memory = Memory(session_id="chat_current_prompt", storage_dir=td, max_recent=20)
        memory.add_message("user", "older note")
        current_id = memory.add_message("user", "current question")

        messages = compose_messages(
            memory,
            prompt="current question",
            tools=None,
            ephemeral_messages=None,
            cfg=ModelConfig(),
            upload_mode="vision",
            exclude_message_ids={current_id},
        )

        user_texts = [
            msg.get("content")
            for msg in messages
            if msg.get("role") == "user" and isinstance(msg.get("content"), str)
        ]
        assert user_texts[-1] == "current question"
        assert sum("current question" in text for text in user_texts) == 1
        assert any("older note" in text for text in user_texts)
