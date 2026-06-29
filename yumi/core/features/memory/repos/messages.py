"""Message-table CRUD + search.

Owns:

* the ``chat_history`` LanceDB table (schema migration, ``thought`` column,
  vector dim alignment);
* per-message CRUD: ``add`` / ``create`` / ``get`` / ``update`` / ``delete``;
* substring + vector search on stored messages.

Dependencies
------------
``MessageRepository`` borrows :class:`~yumi.core.features.memory.backend.LanceDBBackend`
and :class:`~yumi.core.features.memory.embedding_runner.EmbeddingProcessor`. The
``SessionRepository`` is wired in after construction (via
:meth:`bind_sessions`) because session statistics need to read messages.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from yumi.core.features.memory.backend import LanceDBBackend
from yumi.core.features.memory.constants import ACTIVE_SESSION_STATUS, DELETED_SESSION_STATUS
from yumi.core.features.memory.embedding_runner import EmbeddingProcessor
from yumi.logging_config import get_logger

if TYPE_CHECKING:
    from yumi.core.features.memory.repos.sessions import SessionRepository

logger = get_logger(__name__)


class MessageRepository:
    """All operations against the ``chat_history`` table."""

    TABLE_NAME = "chat_history"

    def __init__(
        self,
        backend: LanceDBBackend,
        embeddings: EmbeddingProcessor,
        session_id: str,
    ) -> None:
        self.backend = backend
        self.embeddings = embeddings
        self.session_id = session_id
        self._sessions: SessionRepository | None = None

    def bind_sessions(self, sessions: SessionRepository) -> None:
        """Attach the session repository (resolves the back-edge that creating
        a message refreshes its session row)."""
        self._sessions = sessions

    # ── schema init / migration ────────────────────────────────────────────

    def init_table(self) -> None:
        if not self.backend.has_table(self.TABLE_NAME):
            return
        table = self.backend.open_table(self.TABLE_NAME)
        schema_fields = set(table.schema.names)
        required_fields = {
            "id",
            "vector",
            "session_id",
            "role",
            "content",
            "timestamp",
            "timestamp_num",
        }
        if required_fields.issubset(schema_fields):
            self._ensure_thought_column()
            return
        self._migrate_schema(table)
        self._ensure_thought_column()

    def _migrate_schema(self, table) -> None:
        rows = table.to_pandas().to_dict(orient="records")
        migrated_rows = []
        fallback_timestamp_num = self.backend.current_timestamp_num()
        for index, row in enumerate(rows):
            content = row.get("content", "") or ""
            vector = row.get("vector")
            timestamp = row.get("timestamp") or self.backend.format_timestamp()
            timestamp_num = self.backend.parse_timestamp_num(
                row.get("timestamp_num"),
                timestamp,
                fallback_timestamp_num + index,
            )
            migrated_rows.append(
                {
                    "id": row.get("id") or str(uuid.uuid4()),
                    "vector": self.embeddings.normalise_vector(vector, content),
                    "session_id": row.get("session_id") or self.session_id,
                    "role": row.get("role") or "user",
                    "content": content,
                    "timestamp": timestamp,
                    "timestamp_num": timestamp_num,
                    "thought": str(row.get("thought") or ""),
                }
            )
        self.backend.db.drop_table(self.TABLE_NAME, ignore_missing=True)
        if migrated_rows:
            self.backend.db.create_table(self.TABLE_NAME, data=migrated_rows)

    def _ensure_thought_column(self) -> None:
        if not self.table_exists():
            return
        table = self.backend.open_table(self.TABLE_NAME)
        if "thought" in table.schema.names:
            return
        rows = table.to_pandas().to_dict(orient="records")
        augmented: list[dict] = []
        for row in rows:
            vec = row.get("vector")
            content = row.get("content", "") or ""
            augmented.append(
                {
                    "id": row.get("id") or str(uuid.uuid4()),
                    "vector": self.embeddings.normalise_vector(vec, content),
                    "session_id": row.get("session_id") or self.session_id,
                    "role": row.get("role") or "user",
                    "content": content,
                    "timestamp": row.get("timestamp") or self.backend.format_timestamp(),
                    "timestamp_num": int(
                        self.backend.parse_timestamp_num(
                            row.get("timestamp_num"),
                            row.get("timestamp"),
                            self.backend.current_timestamp_num(),
                        )
                    ),
                    "thought": str(row.get("thought") or ""),
                }
            )
        self.backend.db.drop_table(self.TABLE_NAME, ignore_missing=True)
        if augmented:
            self.backend.db.create_table(self.TABLE_NAME, data=augmented)

    # ── helpers ────────────────────────────────────────────────────────────

    def table_exists(self) -> bool:
        return self.backend.has_table(self.TABLE_NAME)

    def open_table(self):
        return self.backend.open_table(self.TABLE_NAME)

    def serialize(self, row: dict) -> dict:
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "role": row["role"],
            "content": row["content"],
            "thought": str(row.get("thought") or ""),
            "timestamp": row["timestamp"],
            "timestamp_num": int(row["timestamp_num"]),
        }

    def query_rows(
        self,
        where_clause: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict]:
        if not self.table_exists():
            return []
        table = self.open_table()
        query = table.search(query=None, ordering_field_name="timestamp_num")
        if where_clause:
            query = query.where(where_clause)
        if offset:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        return query.to_list()

    def recent_messages_in_sessions(
        self,
        session_ids: list[str],
        limit: int,
    ) -> list[dict]:
        """Return the most recent ``limit`` messages drawn from any of ``session_ids``.

        Used by cross-channel context: a single owner's voice/telegram/chat sessions
        each persist independently, but the prompt composer wants to interleave the
        last few turns regardless of channel.
        """
        if not session_ids or limit <= 0:
            return []
        if not self.table_exists():
            return []
        # Use the backend's escape_where_value so backslashes and other Lance-special
        # characters are escaped consistently with build_where_clause everywhere else.
        escape = self.backend.escape_where_value
        quoted = ",".join("'" + escape(str(s)) + "'" for s in session_ids)
        where = f"session_id IN ({quoted})"
        table = self.open_table()
        try:
            total = table.count_rows(where)
        except Exception:
            # Fallback: filter all rows in Python if count_rows rejects the IN clause.
            rows = self.query_rows(limit=None)
            wanted = set(session_ids)
            filtered = [r for r in rows if r.get("session_id") in wanted]
            return filtered[-limit:]
        offset = max(total - limit, 0)
        return (
            table.search(query=None, ordering_field_name="timestamp_num")
            .where(where)
            .offset(offset)
            .limit(limit)
            .to_list()
        )

    def substring_search_rows(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 5,
    ) -> list[dict]:
        lowered = query.strip().lower()
        if not lowered:
            return []
        where_clause = self.backend.build_where_clause("session_id", session_id) if session_id else None
        rows = self.query_rows(where_clause=where_clause)
        matches = [row for row in rows if lowered in str(row.get("content", "")).lower()]
        matches.sort(key=lambda row: row.get("timestamp_num", 0), reverse=True)
        return matches[:limit]

    # ── CRUD ───────────────────────────────────────────────────────────────

    def add(self, role: str, content: str, thought: str | None = None) -> str:
        timestamp = self.backend.format_timestamp()
        timestamp_num = self.backend.current_timestamp_num()
        return self.create(
            session_id=self.session_id,
            role=role,
            content=content,
            thought=thought,
            timestamp=timestamp,
            timestamp_num=timestamp_num,
        )["id"]

    def create(
        self,
        session_id: str,
        role: str,
        content: str,
        timestamp: str | None = None,
        timestamp_num: int | None = None,
        message_id: str | None = None,
        thought: str | None = None,
    ) -> dict:
        normalized_content = content.strip()
        if not normalized_content:
            raise ValueError("Memory content cannot be empty.")
        normalized_role = role.strip().lower()
        if normalized_role not in {"system", "user", "assistant", "tool"}:
            raise ValueError("Memory role must be one of: system, user, assistant, tool.")

        normalized_session_id = session_id.strip() or self.session_id
        from yumi.core.platform.plugins import get_memory_factory

        get_memory_factory().assert_quota_for_session(normalized_session_id)
        if self._sessions is not None:
            existing_session = self._sessions.ensure_row(normalized_session_id)
            if existing_session["status"] == DELETED_SESSION_STATUS:
                self._sessions.update(normalized_session_id, status=ACTIVE_SESSION_STATUS)

        thought_val = ""
        if normalized_role == "assistant" and thought is not None and str(thought).strip():
            thought_val = str(thought).strip()

        row = {
            "id": message_id or str(uuid.uuid4()),
            "vector": self.embeddings.get_vector(normalized_content),
            "session_id": normalized_session_id,
            "role": normalized_role,
            "content": normalized_content,
            "thought": thought_val,
            "timestamp": timestamp or self.backend.format_timestamp(),
            "timestamp_num": (timestamp_num if timestamp_num is not None else self.backend.current_timestamp_num()),
        }

        if self.table_exists():
            self.open_table().add([row])
        else:
            try:
                self.backend.db.create_table(self.TABLE_NAME, data=[row])
            except Exception:
                self.open_table().add([row])

        if self._sessions is not None:
            self._sessions.refresh_stats(
                normalized_session_id,
                title_candidate=normalized_content if normalized_role == "user" else None,
            )

        try:
            from yumi.core.platform.plugins import get_memory_factory, get_session_scope

            owner = get_session_scope().owner_user_from_session_id(normalized_session_id)
            get_memory_factory().invalidate_size_cache(owner)
        except Exception:
            pass

        return self.serialize(row)

    def get(self, message_id: str) -> dict | None:
        rows = self.query_rows(
            where_clause=self.backend.build_where_clause("id", message_id),
            limit=1,
        )
        if not rows:
            return None
        return self.serialize(rows[0])

    def count(self) -> int:
        """Row count of the LanceDB message index (O(1)); -1 if it can't be read."""
        if not self.table_exists():
            return 0
        try:
            return int(self.open_table().count_rows())
        except Exception:
            return -1

    def list(
        self,
        session_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        include_deleted_sessions: bool = True,
        deleted_session_ids: set[str] | None = None,
    ) -> list[dict]:
        where_clause = self.backend.build_where_clause("session_id", session_id) if session_id else None
        rows = self.query_rows(where_clause=where_clause, limit=limit, offset=offset)
        if not include_deleted_sessions and session_id is None and deleted_session_ids:
            rows = [row for row in rows if row["session_id"] not in deleted_session_ids]
        return [self.serialize(row) for row in rows]

    def update(self, message_id: str, content: str, role: str | None = None) -> dict | None:
        existing = self.get(message_id)
        if existing is None:
            return None
        normalized_content = content.strip()
        if not normalized_content:
            raise ValueError("Memory content cannot be empty.")
        updated_role = role.strip().lower() if role is not None else existing["role"]
        if updated_role not in {"system", "user", "assistant", "tool"}:
            raise ValueError("Memory role must be one of: system, user, assistant, tool.")
        self.delete(message_id)
        updated = self.create(
            session_id=existing["session_id"],
            role=updated_role,
            content=normalized_content,
            timestamp=self.backend.format_timestamp(),
            timestamp_num=self.backend.current_timestamp_num(),
            message_id=existing["id"],
            thought=existing.get("thought") or None,
        )
        return updated

    def delete(self, message_id: str) -> bool:
        existing = self.get(message_id)
        if existing is None:
            return False
        self.open_table().delete(self.backend.build_where_clause("id", message_id))
        if self._sessions is not None:
            self._sessions.refresh_stats(existing["session_id"])
        return True

    def clear_session(self, session_id: str) -> None:
        if self.table_exists():
            self.open_table().delete(self.backend.build_where_clause("session_id", session_id))
        if self._sessions is not None:
            self._sessions.refresh_stats(session_id)

    # ── search ─────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 5,
        include_deleted_sessions: bool = True,
        deleted_session_ids: set[str] | None = None,
    ) -> list[dict]:
        if not self.table_exists():
            return []
        normalized_query = query.strip()
        if not normalized_query:
            return []

        if not self.embeddings.embed_model or not self.embeddings.embedding_available:
            rows = self.substring_search_rows(normalized_query, session_id=session_id, limit=limit)
            messages = [self.serialize(row) for row in rows]
            return self._filter_deleted(
                messages,
                session_id=session_id,
                include_deleted_sessions=include_deleted_sessions,
                deleted_session_ids=deleted_session_ids,
            )

        query_vector = self.embeddings.get_vector(normalized_query)
        if EmbeddingProcessor.is_degenerate(query_vector):
            rows = self.substring_search_rows(normalized_query, session_id=session_id, limit=limit)
            messages = [self.serialize(row) for row in rows]
            return self._filter_deleted(
                messages,
                session_id=session_id,
                include_deleted_sessions=include_deleted_sessions,
                deleted_session_ids=deleted_session_ids,
            )

        table = self.open_table()
        search = table.search(query_vector)
        if session_id:
            search = search.where(self.backend.build_where_clause("session_id", session_id))
        rows = search.limit(limit).to_list()
        messages = [self.serialize(row) for row in rows]
        return self._filter_deleted(
            messages,
            session_id=session_id,
            include_deleted_sessions=include_deleted_sessions,
            deleted_session_ids=deleted_session_ids,
        )

    @staticmethod
    def _filter_deleted(
        messages: list[dict],
        *,
        session_id: str | None,
        include_deleted_sessions: bool,
        deleted_session_ids: set[str] | None,
    ) -> list[dict]:
        if include_deleted_sessions or session_id is not None or not deleted_session_ids:
            return messages
        return [message for message in messages if message["session_id"] not in deleted_session_ids]


__all__ = ["MessageRepository"]
