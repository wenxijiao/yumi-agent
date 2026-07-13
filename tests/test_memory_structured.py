"""Structured memory, tool observations, and ContextBuilder behavior."""

from __future__ import annotations

import tempfile

from yumi.core.features.memory.memory import Memory


def test_message_write_extracts_long_term_preference():
    with tempfile.TemporaryDirectory() as td:
        m = Memory(session_id="s_pref", storage_dir=td, max_recent=20)
        m.add_message("user", "Please remember that from now on you should answer in concise English.")

        memories = m.list_long_term_memories(kind="preference", session_id="s_pref")
        assert len(memories) == 1
        assert "concise English" in memories[0]["content"]
        assert memories[0]["source_message_ids"]


def test_tool_turn_writes_observation_and_context_retrieves_it():
    with tempfile.TemporaryDirectory() as td:
        m = Memory(session_id="s_tool_obs", storage_dir=td, max_recent=20)
        m.persist_openai_messages(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "read_file", "arguments": {"path": "README.md"}},
                        }
                    ],
                },
                {"role": "tool", "name": "read_file", "content": "README says Yumi is local-first."},
            ]
        )

        observations = m.list_tool_observations(session_id="s_tool_obs")
        assert len(observations) == 1
        assert observations[0]["tool_name"] == "read_file"
        assert "local-first" in observations[0]["result_summary"]

        ctx = m.get_context(query="What did the read_file tool return?")
        structured = [msg for msg in ctx if msg["role"] == "system" and "Structured memory" in msg["content"]]
        assert structured
        assert "read_file" in structured[0]["content"]


def test_session_summary_is_included_before_recent_messages():
    with tempfile.TemporaryDirectory() as td:
        m = Memory(session_id="s_summary", storage_dir=td, max_recent=20)
        m.update_session_summary("The user is refactoring the Yumi memory subsystem.")
        m.add_message("user", "What should we do next?")

        ctx = m.get_context(query="continue")
        contents = [msg["content"] for msg in ctx if msg["role"] == "system"]
        assert any("Summary of the earlier part" in content for content in contents)
        assert any("refactoring the Yumi memory" in content for content in contents)
        # The summary block must precede the transcript so it only invalidates
        # the provider prompt cache when a compaction actually rewrites it.
        summary_idx = next(
            i
            for i, msg in enumerate(ctx)
            if msg["role"] == "system" and "Summary of the earlier part" in msg["content"]
        )
        user_idx = next(i for i, msg in enumerate(ctx) if msg["role"] == "user")
        assert summary_idx < user_idx


def test_compaction_watermark_hides_folded_messages():
    with tempfile.TemporaryDirectory() as td:
        m = Memory(session_id="s_watermark", storage_dir=td, max_recent=50)
        m.add_message("user", "old question about apples")
        m.add_message("assistant", "old answer about apples")
        # Compaction folds the rows above: watermark = "now" (after those rows).
        m.update_session_summary("Earlier we discussed apples.")
        m.add_message("user", "new question about pears")

        ctx = m.get_context(query="pears")
        transcript_texts = [msg.get("content") or "" for msg in ctx if msg["role"] in {"user", "assistant"}]
        assert any("pears" in t for t in transcript_texts)
        # Folded rows are represented ONLY by the summary block now.
        assert not any("apples" in t for t in transcript_texts)
        contents = [msg["content"] for msg in ctx if msg["role"] == "system"]
        assert any("discussed apples" in content for content in contents)


def test_hybrid_structured_retrieval_falls_back_to_keyword():
    with tempfile.TemporaryDirectory() as td:
        m = Memory(session_id="s_hybrid", storage_dir=td, max_recent=20)
        m.create_long_term_memory(kind="fact", content="This project stores memory in LanceDB.", session_id="s_hybrid")

        ctx = m.get_context(query="How is LanceDB memory stored?")
        structured = [msg for msg in ctx if msg["role"] == "system" and "Structured memory" in msg["content"]]
        assert structured
        assert "LanceDB" in structured[0]["content"]


def test_context_dedupes_consecutive_identical_user_repeats():
    with tempfile.TemporaryDirectory() as td:
        m = Memory(session_id="s_user_dupe", storage_dir=td, max_recent=20)
        m.add_message("user", "earlier")
        m.add_message("user", "晚安")
        m.add_message("user", "晚安")
        m.add_message("user", "晚安")

        ctx = m.get_context(query="anything")
        user_msgs = [msg for msg in ctx if msg["role"] == "user"]
        assert [msg["content"].split("] ", 1)[-1] for msg in user_msgs] == ["earlier", "晚安"]


def test_context_drops_leading_orphan_assistant_tool_call_when_window_truncates(monkeypatch):
    from yumi.core.features.memory import context as ctx_mod

    real_load = ctx_mod.load_model_config

    def _capped_load_model_config():
        cfg = real_load()
        cfg.memory_max_recent_messages = 5
        return cfg

    monkeypatch.setattr(ctx_mod, "load_model_config", _capped_load_model_config)

    with tempfile.TemporaryDirectory() as td:
        m = Memory(session_id="s_window_orphan", storage_dir=td, max_recent=5)
        for n in range(5):
            m.add_message("user", f"older {n}")
        m.persist_openai_messages(
            [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {"name": "play_song", "arguments": {"q": "桥边姑娘"}},
                        }
                    ],
                },
                {"role": "tool", "name": "play_song", "content": "ok"},
            ]
        )
        m.add_message("user", "later one")
        m.add_message("user", "later two")
        m.add_message("user", "later three")

        ctx = m.get_context(query="anything")
        non_system = [msg for msg in ctx if msg["role"] != "system"]
        assert all("tool_calls" not in msg for msg in non_system)
        assert all(msg["role"] != "tool" for msg in non_system)
        assert non_system, "expected user messages to remain after trimming"
        assert non_system[0]["role"] == "user"
