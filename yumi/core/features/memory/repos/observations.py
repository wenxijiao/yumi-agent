"""Tool observation CRUD (an audit log of tool calls + outcomes)."""

from __future__ import annotations

import uuid

from yumi.core.features.memory.backend import LanceDBBackend
from yumi.core.features.memory.embedding_runner import EmbeddingProcessor
from yumi.core.features.memory.models import TOOL_OBSERVATION_TABLE
from yumi.core.features.memory.repos.long_term import _BackendAdapter
from yumi.core.features.memory.storage import add_row, query_rows


class ToolObservationRepository:
    """All operations against the ``tool_observations`` table."""

    TABLE_NAME = TOOL_OBSERVATION_TABLE

    def __init__(self, backend: LanceDBBackend, embeddings: EmbeddingProcessor, default_session_id: str) -> None:
        self.backend = backend
        self.embeddings = embeddings
        self.default_session_id = default_session_id

    def serialize(self, row: dict) -> dict:
        return {
            "id": row["id"],
            "tool_name": row["tool_name"],
            "args_summary": row.get("args_summary") or "",
            "result_summary": row["result_summary"],
            "content": row.get("content") or row["result_summary"],
            "success": bool(row.get("success", True)),
            "session_id": row["session_id"],
            "call_id": row.get("call_id") or "",
            "importance": float(row.get("importance") or 0.0),
            "timestamp": row["timestamp"],
            "timestamp_num": int(row["timestamp_num"]),
        }

    def create(
        self,
        *,
        tool_name: str,
        args_summary: str = "",
        result_summary: str,
        success: bool = True,
        session_id: str | None = None,
        call_id: str = "",
        importance: float = 0.5,
    ) -> dict | None:
        normalized_result = " ".join(str(result_summary or "").split())
        if not normalized_result:
            return None
        sid = (session_id or self.default_session_id).strip() or self.default_session_id
        now = self.backend.format_timestamp()
        now_num = self.backend.current_timestamp_num()
        name = (tool_name or "tool").strip() or "tool"
        args = " ".join(str(args_summary or "").split())
        content = f"{name}({args}) -> {normalized_result}" if args else f"{name} -> {normalized_result}"
        row = {
            "id": str(uuid.uuid4()),
            "vector": self.embeddings.get_vector(content),
            "tool_name": name,
            "args_summary": args,
            "result_summary": normalized_result,
            "content": content,
            "success": bool(success),
            "session_id": sid,
            "call_id": str(call_id or ""),
            "importance": float(max(0.0, min(1.0, importance))),
            "timestamp": now,
            "timestamp_num": now_num,
        }
        add_row(_BackendAdapter(self.backend), self.TABLE_NAME, row)
        return self.serialize(row)

    def list(self, session_id: str | None = None, limit: int = 50) -> list[dict]:
        # Push the session filter into LanceDB before applying the row limit;
        # otherwise the global most-recent N rows are taken first and the
        # session filter trims them in Python, silently dropping older but
        # session-matching rows.
        where_clause = self.backend.build_where_clause("session_id", session_id) if session_id is not None else None
        rows = query_rows(
            _BackendAdapter(self.backend),
            self.TABLE_NAME,
            ordering_field_name="timestamp_num",
            where_clause=where_clause,
            limit=limit,
        )
        rows.sort(key=lambda row: int(row.get("timestamp_num") or 0), reverse=True)
        return [self.serialize(row) for row in rows[:limit]]


__all__ = ["ToolObservationRepository"]
