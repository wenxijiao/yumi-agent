"""Long-term memory CRUD (preference / fact / decision / task_state / …)."""

from __future__ import annotations

import uuid

from mirai.core.memories.backend import LanceDBBackend
from mirai.core.memories.embedding_runner import EmbeddingProcessor
from mirai.core.memories.models import LONG_TERM_MEMORY_KINDS, LONG_TERM_TABLE, decode_json_list, encode_json
from mirai.core.memories.storage import add_row, query_rows, replace_row


class LongTermMemoryRepository:
    """All operations against the ``long_term_memories`` table."""

    TABLE_NAME = LONG_TERM_TABLE

    def __init__(self, backend: LanceDBBackend, embeddings: EmbeddingProcessor, default_session_id: str) -> None:
        self.backend = backend
        self.embeddings = embeddings
        self.default_session_id = default_session_id

    # ── helpers ────────────────────────────────────────────────────────────

    def serialize(self, row: dict) -> dict:
        return {
            "id": row["id"],
            "kind": row["kind"],
            "content": row["content"],
            "source_message_ids": decode_json_list(row.get("source_message_ids")),
            "session_id": row["session_id"],
            "confidence": float(row.get("confidence") or 0.0),
            "importance": float(row.get("importance") or 0.0),
            "created_at": row["created_at"],
            "created_at_num": int(row["created_at_num"]),
            "updated_at": row["updated_at"],
            "updated_at_num": int(row["updated_at_num"]),
            "last_used_at": str(row.get("last_used_at") or ""),
            "last_used_at_num": int(row.get("last_used_at_num") or 0),
        }

    def _find_duplicate(self, kind: str, content: str, session_id: str) -> dict | None:
        if not self.backend.has_table(self.TABLE_NAME):
            return None
        normalized = " ".join(content.lower().split())
        rows = query_rows(
            self._memory_facade(),
            self.TABLE_NAME,
            where_clause=self.backend.build_where_clause("kind", kind),
        )
        for row in rows:
            if str(row.get("session_id") or "") != session_id:
                continue
            if " ".join(str(row.get("content") or "").lower().split()) == normalized:
                return row
        return None

    def _memory_facade(self):
        """Return an object compatible with :mod:`mirai.core.memories.storage` shims.

        The storage helpers expect ``memory.db`` and ``memory._has_table`` /
        ``memory._build_where_clause``. We pass an adapter that exposes them.
        """
        return _BackendAdapter(self.backend)

    # ── CRUD ───────────────────────────────────────────────────────────────

    def create(
        self,
        *,
        kind: str,
        content: str,
        session_id: str | None = None,
        source_message_ids: list[str] | None = None,
        confidence: float = 0.5,
        importance: float = 0.5,
    ) -> dict:
        normalized_kind = str(kind or "fact").strip().lower()
        if normalized_kind not in LONG_TERM_MEMORY_KINDS:
            raise ValueError(f"Memory kind must be one of: {', '.join(sorted(LONG_TERM_MEMORY_KINDS))}.")
        normalized_content = " ".join(str(content or "").split())
        if not normalized_content:
            raise ValueError("Long-term memory content cannot be empty.")
        sid = (session_id or self.default_session_id).strip() or self.default_session_id
        now = self.backend.format_timestamp()
        now_num = self.backend.current_timestamp_num()
        existing = self._find_duplicate(normalized_kind, normalized_content, sid)
        row_id = existing.get("id") if existing else str(uuid.uuid4())
        row = {
            "id": row_id,
            "vector": self.embeddings.get_vector(normalized_content),
            "kind": normalized_kind,
            "content": normalized_content,
            "source_message_ids": encode_json([x for x in (source_message_ids or []) if x]),
            "session_id": sid,
            "confidence": float(max(0.0, min(1.0, confidence))),
            "importance": float(max(0.0, min(1.0, importance))),
            "created_at": existing.get("created_at") if existing else now,
            "created_at_num": int(existing.get("created_at_num") or now_num) if existing else now_num,
            "updated_at": now,
            "updated_at_num": now_num,
            "last_used_at": str(existing.get("last_used_at") or "") if existing else "",
            "last_used_at_num": int(existing.get("last_used_at_num") or 0) if existing else 0,
        }
        if existing:
            replace_row(self._memory_facade(), self.TABLE_NAME, "id", row_id, row)
        else:
            add_row(self._memory_facade(), self.TABLE_NAME, row)
        return self.serialize(row)

    def list(self, kind: str | None = None, session_id: str | None = None, limit: int = 50) -> list[dict]:
        clauses: list[str] = []
        if kind:
            clauses.append(self.backend.build_where_clause("kind", kind.strip().lower()))
        if session_id is not None:
            # Push the session filter into LanceDB before applying limit, otherwise
            # the global most-recent N rows are taken first and a busy DB silently
            # drops older but session-matching rows.
            clauses.append(self.backend.build_where_clause("session_id", session_id))
        where_clause = " AND ".join(clauses) if clauses else None
        rows = query_rows(
            self._memory_facade(),
            self.TABLE_NAME,
            ordering_field_name="updated_at_num",
            where_clause=where_clause,
            limit=limit,
        )
        rows.sort(key=lambda row: int(row.get("updated_at_num") or 0), reverse=True)
        return [self.serialize(row) for row in rows[:limit]]


class _BackendAdapter:
    """Minimal duck-type for ``mirai.core.memories.storage``'s memory parameter.

    The helpers in :mod:`mirai.core.memories.storage` were written when there
    was a single :class:`Memory` god object; they call ``memory._has_table``,
    ``memory.db``, and ``memory._build_where_clause``. Wrapping the backend
    in an adapter keeps that procedural surface alive without coupling repos
    to the legacy Memory class.
    """

    def __init__(self, backend: LanceDBBackend) -> None:
        self.db = backend.db
        self._backend = backend

    def _has_table(self, table_name: str, db=None) -> bool:
        return self._backend.has_table(table_name, db)

    def _build_where_clause(self, field: str, value: str) -> str:
        return self._backend.build_where_clause(field, value)


__all__ = ["LongTermMemoryRepository"]
