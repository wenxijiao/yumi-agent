"""Cross-channel prompt context: voice/tg/chat sessions merge into one transcript."""

from __future__ import annotations

from types import SimpleNamespace

from kumi.core.features.memory.context import ContextBuilder, _channel_label
from kumi.core.features.prompts.composer import _peer_session_ids


class _StubTable:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def search(self, query=None, ordering_field_name=None):
        return _StubQuery(self._rows)

    def count_rows(self, where: str) -> int:
        return len(_apply_where(self._rows, where))


class _StubQuery:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows
        self._where = None
        self._offset = 0
        self._limit = None

    def where(self, clause: str) -> "_StubQuery":
        self._where = clause
        return self

    def offset(self, n: int) -> "_StubQuery":
        self._offset = n
        return self

    def limit(self, n: int) -> "_StubQuery":
        self._limit = n
        return self

    def to_list(self) -> list[dict]:
        rows = self._rows
        if self._where:
            rows = _apply_where(rows, self._where)
        rows = sorted(rows, key=lambda r: int(r.get("timestamp_num") or 0))
        if self._offset:
            rows = rows[self._offset :]
        if self._limit is not None:
            rows = rows[: self._limit]
        return rows


def _apply_where(rows: list[dict], clause: str) -> list[dict]:
    """Tiny SQL-ish parser for ``session_id = 'X'`` and ``session_id IN ('a','b')``."""
    clause = clause.strip()
    if "IN (" in clause:
        inside = clause.split("IN (", 1)[1].rstrip(")")
        ids = {p.strip().strip("'") for p in inside.split(",")}
        return [r for r in rows if r.get("session_id") in ids]
    if "=" in clause:
        # session_id = 'X'
        right = clause.split("=", 1)[1].strip().strip("'")
        return [r for r in rows if r.get("session_id") == right]
    return rows


class _StubMemory:
    """Minimum surface ContextBuilder reads."""

    def __init__(self, session_id: str, rows: list[dict]) -> None:
        self.session_id = session_id
        self._rows = rows
        self._table = _StubTable(rows)

    def get_system_message(self) -> dict:
        return {"role": "system", "content": "sys"}

    def _table_exists(self) -> bool:
        return True

    def _open_table(self):
        return self._table

    def _build_where_clause(self, field: str, value: str) -> str:
        return f"{field} = '{value}'"

    def get_session_summary(self, session_id: str | None = None) -> dict | None:
        return None

    def build_related_memory_message(self, *args, **kwargs) -> dict | None:
        return None

    def recent_messages_in_sessions(self, session_ids: list[str], limit: int) -> list[dict]:
        wanted = set(session_ids)
        rows = [r for r in self._rows if r.get("session_id") in wanted]
        rows.sort(key=lambda r: int(r.get("timestamp_num") or 0))
        return rows[-limit:]


def _row(sid: str, role: str, content: str, ts: int, mid: str) -> dict:
    return {
        "id": mid,
        "session_id": sid,
        "role": role,
        "content": content,
        "timestamp": str(ts),
        "timestamp_num": ts,
    }


def test_peer_session_ids_voice_owner():
    assert _peer_session_ids("voice_alice") == ["tg_alice", "chat_alice"]
    assert _peer_session_ids("tg_alice") == ["voice_alice", "chat_alice"]
    assert _peer_session_ids("chat_alice") == ["voice_alice", "tg_alice"]


def test_peer_session_ids_unknown_prefix_returns_empty():
    assert _peer_session_ids("foo_bar") == []
    assert _peer_session_ids("default") == []


def test_channel_label_lookup():
    assert _channel_label("voice_alice") == "voice"
    assert _channel_label("tg_alice") == "telegram"
    assert _channel_label("chat_alice") == "chat"
    assert _channel_label("default") is None


def test_recent_transcript_merges_peer_sessions_in_timestamp_order(monkeypatch):
    # Force load_model_config to return a default config so we don't depend on
    # ~/.kumi/config.json existing.
    cfg = SimpleNamespace(memory_max_recent_messages=10, memory_max_related_messages=0)
    monkeypatch.setattr("kumi.core.features.memory.context.load_model_config", lambda: cfg)

    rows = [
        _row("voice_alice", "user", "weather please", ts=100, mid="v1"),
        _row("voice_alice", "assistant", "sunny", ts=110, mid="v2"),
        _row("tg_alice", "user", "and tomorrow?", ts=120, mid="t1"),
        _row("tg_alice", "assistant", "rain", ts=130, mid="t2"),
        _row("voice_alice", "user", "thanks", ts=140, mid="v3"),
    ]
    memory = _StubMemory("voice_alice", rows)
    builder = ContextBuilder(memory)

    out = builder.build(query="now what?", peer_session_ids=["tg_alice"])
    # First message is the system prompt; the rest should be the merged transcript.
    transcript = out[1:]
    contents = [m.get("content") for m in transcript]

    # Voice rows show up plain; telegram rows are tagged "(via telegram)".
    assert any("(via telegram)" in str(c) and "tomorrow" in str(c) for c in contents)
    assert any("(via telegram)" in str(c) and "rain" in str(c) for c in contents)

    # Order is by timestamp_num ascending — "thanks" (ts=140) is last.
    assert "thanks" in str(contents[-1])

    # Telegram "and tomorrow?" (ts=120) should appear between voice ts=110 and ts=140.
    voice_thanks_idx = next(i for i, c in enumerate(contents) if "thanks" in str(c))
    tg_tomorrow_idx = next(i for i, c in enumerate(contents) if "tomorrow" in str(c))
    voice_sunny_idx = next(i for i, c in enumerate(contents) if "sunny" in str(c))
    assert voice_sunny_idx < tg_tomorrow_idx < voice_thanks_idx


def test_recent_transcript_no_peers_unchanged(monkeypatch):
    cfg = SimpleNamespace(memory_max_recent_messages=10, memory_max_related_messages=0)
    monkeypatch.setattr("kumi.core.features.memory.context.load_model_config", lambda: cfg)

    rows = [
        _row("voice_alice", "user", "hi", ts=10, mid="v1"),
        _row("tg_alice", "user", "ignore me", ts=20, mid="t1"),
        _row("voice_alice", "assistant", "hello", ts=30, mid="v2"),
    ]
    memory = _StubMemory("voice_alice", rows)
    builder = ContextBuilder(memory)
    out = builder.build(query=None, peer_session_ids=None)
    contents = [m.get("content") for m in out[1:]]
    assert all("ignore me" not in str(c) for c in contents)
    assert any("hi" in str(c) for c in contents)
    assert any("hello" in str(c) for c in contents)
