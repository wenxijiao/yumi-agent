"""Tool-turn persistence and vector-search fallback."""

import tempfile

from kumi.core.memories.memory import Memory, _is_degenerate_vector
from kumi.core.memories.tool_replay import message_hidden_from_chat_ui


def test_is_degenerate_vector():
    assert _is_degenerate_vector(None) is True
    assert _is_degenerate_vector([]) is True
    assert _is_degenerate_vector([0.0, 0.0, 0.0]) is True
    assert _is_degenerate_vector([0.0, 1e-15, -1e-15]) is True
    assert _is_degenerate_vector([0.0, 0.01]) is False


def test_persist_tool_turn_roundtrip():
    tc = [{"function": {"name": "demo_tool", "arguments": {"x": 1}}}]
    with tempfile.TemporaryDirectory() as td:
        m = Memory(session_id="s_tool", storage_dir=td, max_recent=50)
        m.persist_openai_messages(
            [
                {"role": "assistant", "content": "", "tool_calls": tc},
                {"role": "tool", "name": "demo_tool", "content": "done"},
            ]
        )
        ctx = m.get_context(query=None)
        roles = [x.get("role") for x in ctx]
        assert "assistant" in roles
        assert "tool" in roles
        asst = next(x for x in ctx if x.get("role") == "assistant" and x.get("tool_calls"))
        assert asst["tool_calls"][0]["function"]["name"] == "demo_tool"
        tool = next(x for x in ctx if x.get("role") == "tool")
        assert tool["name"] == "demo_tool"
        assert tool["content"] == "done"


def test_search_messages_degenerate_query_uses_substring():
    with tempfile.TemporaryDirectory() as td:
        m = Memory(session_id="s_sub", storage_dir=td, max_recent=50)
        m._embedding_available = True
        m.embed_model = "fake-model"

        def _zero_embed(_model: str, _text: str):
            return [0.0] * 8

        m._embed_provider = type("P", (), {"embed": staticmethod(_zero_embed)})()
        m.add_message("user", "hello unique_marker_xyz")
        out = m.search_messages("unique_marker_xyz", session_id="s_sub", limit=5)
        assert len(out) >= 1
        assert any("unique_marker_xyz" in (x.get("content") or "") for x in out)


def test_table_exists_prefers_list_tables_when_available():
    class FakeListTablesResponse:
        def __init__(self, tables):
            self.tables = tables

    class FakeDb:
        def list_tables(self):
            return FakeListTablesResponse(["chat_history"])

        def table_names(self):
            raise AssertionError("table_names() should not be used when list_tables() exists")

    m = object.__new__(Memory)
    m.db = FakeDb()
    m.table_name = "chat_history"
    m.session_table_name = "chat_sessions"

    assert m._table_exists() is True
    assert m._session_table_exists() is False


def test_message_hidden_from_chat_ui():
    assert message_hidden_from_chat_ui({"role": "assistant", "content": "__kumi:v1:tc__\n{}"}) is True
    assert message_hidden_from_chat_ui({"role": "assistant", "content": "Hello"}) is False
    assert message_hidden_from_chat_ui({"role": "user", "content": "__kumi:v1:tc__\n{}"}) is False


def test_assistant_thought_persisted():
    with tempfile.TemporaryDirectory() as td:
        m = Memory(session_id="s_think", storage_dir=td, max_recent=50)
        msg_id = m.add_message("assistant", "Visible answer", thought="internal reasoning steps")
        rows = m.list_messages(session_id="s_think", limit=10)
        row = next(r for r in rows if r["id"] == msg_id)
        assert row["content"] == "Visible answer"
        assert row["thought"] == "internal reasoning steps"
        ctx = m.get_context(query=None)
        asst = [x for x in ctx if x.get("role") == "assistant" and x.get("content") == "Visible answer"]
        assert len(asst) == 1
        assert "thought" not in asst[0]
