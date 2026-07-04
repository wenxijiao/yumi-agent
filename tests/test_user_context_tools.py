from __future__ import annotations

import tempfile

from yumi.core.features.memory.memory import Memory
from yumi.tools import user_context_tools


def test_user_context_tools_remember_list_and_forget(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        memory = Memory(session_id="default", storage_dir=td, max_recent=20)
        monkeypatch.setattr(user_context_tools, "_memory_store", lambda: memory)

        saved = user_context_tools.remember_user_context(
            "The user prefers calm, concise replies during debugging.",
            kind="communication_style",
        )
        memory_id = saved.split(" memory ", 1)[1].split(":", 1)[0]

        listed = user_context_tools.list_user_context()
        assert memory_id in listed
        assert "calm, concise replies" in listed

        deleted = user_context_tools.forget_user_context(memory_id)
        assert f"Forgot stable user context memory {memory_id}." == deleted
        assert memory_id not in user_context_tools.list_user_context()


def test_user_context_tool_rejects_tool_observation_kind(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        memory = Memory(session_id="default", storage_dir=td, max_recent=20)
        monkeypatch.setattr(user_context_tools, "_memory_store", lambda: memory)

        try:
            user_context_tools.remember_user_context("Should not save", kind="tool_observation")
        except ValueError as exc:
            assert "tool_observation" not in str(exc)
        else:
            raise AssertionError("expected invalid kind")
