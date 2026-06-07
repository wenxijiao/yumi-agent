"""Per-session summary CRUD (used to compress old turns)."""

from __future__ import annotations

from kumi.core.features.memory.backend import LanceDBBackend
from kumi.core.features.memory.embedding_runner import EmbeddingProcessor
from kumi.core.features.memory.models import SESSION_SUMMARY_TABLE
from kumi.core.features.memory.repos.long_term import _BackendAdapter
from kumi.core.features.memory.storage import query_rows, replace_row


class SessionSummaryRepository:
    """All operations against the ``session_summaries`` table."""

    TABLE_NAME = SESSION_SUMMARY_TABLE

    def __init__(self, backend: LanceDBBackend, embeddings: EmbeddingProcessor, default_session_id: str) -> None:
        self.backend = backend
        self.embeddings = embeddings
        self.default_session_id = default_session_id

    def get(self, session_id: str | None = None) -> dict | None:
        sid = (session_id or self.default_session_id).strip() or self.default_session_id
        rows = query_rows(
            _BackendAdapter(self.backend),
            self.TABLE_NAME,
            where_clause=self.backend.build_where_clause("session_id", sid),
            limit=1,
        )
        return rows[0] if rows else None

    def update(
        self,
        summary: str,
        session_id: str | None = None,
        *,
        covered_until_num: int | None = None,
    ) -> dict:
        normalized = " ".join(str(summary or "").split())
        if not normalized:
            raise ValueError("Session summary cannot be empty.")
        sid = (session_id or self.default_session_id).strip() or self.default_session_id
        now = self.backend.format_timestamp()
        now_num = self.backend.current_timestamp_num()
        existing = self.get(sid) or {}
        row = {
            "session_id": sid,
            "summary": normalized,
            "vector": self.embeddings.get_vector(normalized),
            "covered_until_num": int(covered_until_num if covered_until_num is not None else now_num),
            "created_at": existing.get("created_at") or now,
            "created_at_num": int(existing.get("created_at_num") or now_num),
            "updated_at": now,
            "updated_at_num": now_num,
        }
        replace_row(_BackendAdapter(self.backend), self.TABLE_NAME, "session_id", sid, row)
        return row


__all__ = ["SessionSummaryRepository"]
