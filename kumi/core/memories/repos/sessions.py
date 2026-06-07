"""Session-table CRUD + statistics maintenance.

Owns the ``chat_sessions`` LanceDB table. Statistics (``message_count``,
``last_message_at``) are derived from the message table — the
:class:`SessionRepository` borrows :class:`~kumi.core.memories.repos.messages.MessageRepository`
for those reads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from kumi.core.memories.backend import LanceDBBackend
from kumi.core.memories.constants import (
    ACTIVE_SESSION_STATUS,
    DEFAULT_SESSION_TITLE,
    DELETED_SESSION_STATUS,
)
from kumi.core.memories.sessions import (
    derive_session_title,
    normalize_session_status,
    normalize_session_title,
)

if TYPE_CHECKING:
    from kumi.core.memories.repos.messages import MessageRepository


class SessionRepository:
    """All operations against the ``chat_sessions`` table."""

    TABLE_NAME = "chat_sessions"

    def __init__(self, backend: LanceDBBackend, messages: MessageRepository) -> None:
        self.backend = backend
        self.messages = messages

    # ── schema init / migration ────────────────────────────────────────────

    def init_table(self) -> None:
        if not self.backend.has_table(self.TABLE_NAME):
            bootstrap_rows = self._bootstrap_rows()
            if bootstrap_rows:
                self.backend.db.create_table(self.TABLE_NAME, data=bootstrap_rows)
            return

        table = self.backend.open_table(self.TABLE_NAME)
        schema_fields = set(table.schema.names)
        required_fields = {
            "session_id",
            "title",
            "status",
            "is_pinned",
            "created_at",
            "created_at_num",
            "updated_at",
            "updated_at_num",
            "last_message_at",
            "last_message_at_num",
            "message_count",
        }
        if required_fields.issubset(schema_fields):
            return
        self._migrate_schema(table)

    def _migrate_schema(self, table) -> None:
        rows = table.to_pandas().to_dict(orient="records")
        existing = {str(row.get("session_id")): row for row in rows if row.get("session_id")}
        migrated_rows = []
        fallback_timestamp_num = self.backend.current_timestamp_num()

        for bootstrap_row in self._bootstrap_rows():
            current = existing.get(bootstrap_row["session_id"], {})
            migrated_rows.append(
                {
                    "session_id": bootstrap_row["session_id"],
                    "title": (current.get("title") or bootstrap_row["title"]).strip() or DEFAULT_SESSION_TITLE,
                    "status": normalize_session_status(current.get("status") or bootstrap_row["status"]),
                    "is_pinned": bool(current.get("is_pinned", bootstrap_row["is_pinned"])),
                    "created_at": current.get("created_at") or bootstrap_row["created_at"],
                    "created_at_num": int(current.get("created_at_num", bootstrap_row["created_at_num"])),
                    "updated_at": current.get("updated_at") or bootstrap_row["updated_at"],
                    "updated_at_num": int(current.get("updated_at_num", bootstrap_row["updated_at_num"])),
                    "last_message_at": current.get("last_message_at") or bootstrap_row["last_message_at"],
                    "last_message_at_num": int(
                        current.get("last_message_at_num", bootstrap_row["last_message_at_num"])
                    ),
                    "message_count": int(current.get("message_count", bootstrap_row["message_count"])),
                }
            )

        for session_id, row in existing.items():
            if any(item["session_id"] == session_id for item in migrated_rows):
                continue
            migrated_rows.append(
                {
                    "session_id": session_id,
                    "title": (str(row.get("title", "")).strip() or DEFAULT_SESSION_TITLE),
                    "status": normalize_session_status(row.get("status") or ACTIVE_SESSION_STATUS),
                    "is_pinned": bool(row.get("is_pinned", False)),
                    "created_at": row.get("created_at") or self.backend.format_timestamp(),
                    "created_at_num": int(row.get("created_at_num", fallback_timestamp_num)),
                    "updated_at": row.get("updated_at") or row.get("created_at") or self.backend.format_timestamp(),
                    "updated_at_num": int(row.get("updated_at_num", row.get("created_at_num", fallback_timestamp_num))),
                    "last_message_at": row.get("last_message_at") or "",
                    "last_message_at_num": int(row.get("last_message_at_num", 0)),
                    "message_count": int(row.get("message_count", 0)),
                }
            )

        self.backend.db.drop_table(self.TABLE_NAME, ignore_missing=True)
        if migrated_rows:
            self.backend.db.create_table(self.TABLE_NAME, data=migrated_rows)

    def _bootstrap_rows(self) -> list[dict]:
        rows = self.messages.query_rows()
        sessions: dict[str, dict] = {}
        for row in rows:
            session_id = str(row["session_id"])
            timestamp = row["timestamp"]
            timestamp_num = int(row["timestamp_num"])
            entry = sessions.setdefault(
                session_id,
                {
                    "session_id": session_id,
                    "title": DEFAULT_SESSION_TITLE,
                    "status": ACTIVE_SESSION_STATUS,
                    "is_pinned": False,
                    "created_at": timestamp,
                    "created_at_num": timestamp_num,
                    "updated_at": timestamp,
                    "updated_at_num": timestamp_num,
                    "last_message_at": timestamp,
                    "last_message_at_num": timestamp_num,
                    "message_count": 0,
                },
            )
            entry["message_count"] += 1
            if timestamp_num < entry["created_at_num"]:
                entry["created_at"] = timestamp
                entry["created_at_num"] = timestamp_num
            if timestamp_num >= entry["last_message_at_num"]:
                entry["last_message_at"] = timestamp
                entry["last_message_at_num"] = timestamp_num
                entry["updated_at"] = timestamp
                entry["updated_at_num"] = timestamp_num
            if entry["title"] == DEFAULT_SESSION_TITLE and row.get("role") == "user":
                entry["title"] = derive_session_title(row.get("content", ""))
        return list(sessions.values())

    # ── helpers ────────────────────────────────────────────────────────────

    def table_exists(self) -> bool:
        return self.backend.has_table(self.TABLE_NAME)

    def open_table(self):
        return self.backend.open_table(self.TABLE_NAME)

    def serialize(self, row: dict) -> dict:
        return {
            "session_id": row["session_id"],
            "title": row["title"],
            "status": row["status"],
            "is_pinned": bool(row["is_pinned"]),
            "created_at": row["created_at"],
            "created_at_num": int(row["created_at_num"]),
            "updated_at": row["updated_at"],
            "updated_at_num": int(row["updated_at_num"]),
            "last_message_at": row["last_message_at"],
            "last_message_at_num": int(row["last_message_at_num"]),
            "message_count": int(row["message_count"]),
        }

    def query_rows(self, where_clause: str | None = None, limit: int | None = None) -> list[dict]:
        if not self.table_exists():
            return []
        table = self.open_table()
        query = table.search(query=None, ordering_field_name="updated_at_num")
        if where_clause:
            query = query.where(where_clause)
        if limit is not None:
            query = query.limit(limit)
        return query.to_list()

    def put_row(self, row: dict) -> None:
        if self.table_exists():
            table = self.open_table()
            table.delete(self.backend.build_where_clause("session_id", row["session_id"]))
            table.add([row])
            return
        try:
            self.backend.db.create_table(self.TABLE_NAME, data=[row])
        except Exception:
            table = self.open_table()
            table.delete(self.backend.build_where_clause("session_id", row["session_id"]))
            table.add([row])

    def get_row(self, session_id: str) -> dict | None:
        rows = self.query_rows(
            where_clause=self.backend.build_where_clause("session_id", session_id),
            limit=1,
        )
        return rows[0] if rows else None

    def ensure_row(self, session_id: str) -> dict:
        existing = self.get_row(session_id)
        if existing is not None:
            return existing
        timestamp = self.backend.format_timestamp()
        timestamp_num = self.backend.current_timestamp_num()
        row = {
            "session_id": session_id,
            "title": DEFAULT_SESSION_TITLE,
            "status": ACTIVE_SESSION_STATUS,
            "is_pinned": False,
            "created_at": timestamp,
            "created_at_num": timestamp_num,
            "updated_at": timestamp,
            "updated_at_num": timestamp_num,
            "last_message_at": "",
            "last_message_at_num": 0,
            "message_count": 0,
        }
        self.put_row(row)
        return row

    def refresh_stats(self, session_id: str, title_candidate: str | None = None) -> dict:
        session = self.ensure_row(session_id)
        rows = self.messages.query_rows(where_clause=self.backend.build_where_clause("session_id", session_id))
        now = self.backend.format_timestamp()
        now_num = self.backend.current_timestamp_num()
        updated = dict(session)

        if rows:
            latest = max(rows, key=lambda row: int(row.get("timestamp_num", 0)))
            first_user = next((row for row in rows if row.get("role") == "user"), None)
            title = session["title"]
            if title == DEFAULT_SESSION_TITLE:
                source = title_candidate or (first_user.get("content", "") if first_user else "")
                title = derive_session_title(source)
            updated.update(
                {
                    "title": title,
                    "message_count": len(rows),
                    "last_message_at": latest["timestamp"],
                    "last_message_at_num": int(latest["timestamp_num"]),
                    "updated_at": now,
                    "updated_at_num": now_num,
                }
            )
        else:
            updated.update(
                {
                    "message_count": 0,
                    "last_message_at": "",
                    "last_message_at_num": 0,
                    "updated_at": now,
                    "updated_at_num": now_num,
                }
            )

        self.put_row(updated)
        return updated

    # ── public CRUD ────────────────────────────────────────────────────────

    def create(self, title: str | None = None, session_id: str | None = None) -> dict:
        import uuid

        normalized_session_id = (session_id or "").strip() or str(uuid.uuid4())
        existing = self.get(normalized_session_id)
        if existing is not None:
            return existing

        timestamp = self.backend.format_timestamp()
        timestamp_num = self.backend.current_timestamp_num()
        row = {
            "session_id": normalized_session_id,
            "title": normalize_session_title(title),
            "status": ACTIVE_SESSION_STATUS,
            "is_pinned": False,
            "created_at": timestamp,
            "created_at_num": timestamp_num,
            "updated_at": timestamp,
            "updated_at_num": timestamp_num,
            "last_message_at": "",
            "last_message_at_num": 0,
            "message_count": 0,
        }
        self.put_row(row)
        return self.serialize(row)

    def get(self, session_id: str) -> dict | None:
        row = self.get_row(session_id)
        if row is None:
            return None
        return self.serialize(row)

    def update(
        self,
        session_id: str,
        title: str | None = None,
        is_pinned: bool | None = None,
        status: str | None = None,
    ) -> dict | None:
        existing = self.get_row(session_id)
        if existing is None:
            return None
        updated = dict(existing)
        updated["title"] = normalize_session_title(title) if title is not None else existing["title"]
        updated["is_pinned"] = bool(is_pinned) if is_pinned is not None else bool(existing["is_pinned"])
        updated["status"] = (
            normalize_session_status(status) if status is not None else normalize_session_status(existing["status"])
        )
        updated["updated_at"] = self.backend.format_timestamp()
        updated["updated_at_num"] = self.backend.current_timestamp_num()
        self.put_row(updated)
        return self.serialize(updated)

    def list(
        self,
        status: str = ACTIVE_SESSION_STATUS,
        session_id_prefix: str | None = None,
    ) -> list[dict]:
        normalized_status = status.strip().lower()
        if normalized_status not in {ACTIVE_SESSION_STATUS, DELETED_SESSION_STATUS, "all"}:
            raise ValueError("Session status filter must be one of: active, deleted, all.")

        rows = self.query_rows()
        sessions = [self.serialize(row) for row in rows]
        if session_id_prefix:
            sessions = [s for s in sessions if str(s["session_id"]).startswith(session_id_prefix)]
        if normalized_status != "all":
            sessions = [session for session in sessions if session["status"] == normalized_status]

        sessions.sort(
            key=lambda item: (
                1 if item["is_pinned"] else 0,
                max(item["last_message_at_num"], item["updated_at_num"]),
            ),
            reverse=True,
        )
        return sessions


__all__ = ["SessionRepository"]
