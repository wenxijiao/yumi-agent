"""Memory façade.

The legacy ``Memory`` god class has been decomposed into focused collaborators
(see :mod:`yumi.core.features.memory.backend`, :mod:`yumi.core.features.memory.embedding_runner`,
:mod:`yumi.core.features.memory.repos`). This module keeps the historical
:class:`Memory` public API stable so every caller — chatbot, routers,
LINE/Telegram bridges, enterprise per-user memory factory, tests — continues
to work without changes.

What stayed
-----------
* Constructor signature ``Memory(session_id, system_prompt=None, storage_dir=None, max_recent=10)``
* All public methods (``add_message``, ``list_messages``, ``create_message``,
  ``create_long_term_memory``, ``create_session``, ``list_sessions`` …)
* Legacy private methods used by external callers (``_has_table``,
  ``_open_table``, ``_open_session_table``, ``_build_where_clause``,
  ``_query_message_rows``, etc.) — they delegate to the appropriate
  collaborator so :mod:`yumi.core.features.memory.context`,
  :mod:`yumi.core.features.memory.storage` and :mod:`yumi.core.features.memory.writer`
  keep functioning unchanged.

What moved
----------
* LanceDB connection, time/SQL helpers → :class:`~yumi.core.features.memory.backend.LanceDBBackend`
* Embedding state, dim migration, re-embed → :class:`~yumi.core.features.memory.embedding_runner.EmbeddingProcessor`
* Per-table CRUD → repositories under :mod:`yumi.core.features.memory.repos`
"""

from __future__ import annotations

from yumi.core.features.config import load_model_config, migrate_legacy_memory_dir
from yumi.core.features.memory import transcript as _transcript
from yumi.core.features.memory.backend import LanceDBBackend
from yumi.core.features.memory.constants import DELETED_SESSION_STATUS
from yumi.core.features.memory.embedding_runner import EmbeddingProcessor
from yumi.core.features.memory.embedding_state import (
    get_embed_provider,
)
from yumi.core.features.memory.embedding_state import (
    is_degenerate_vector as _is_degenerate_vector,  # noqa: F401 — re-exported for legacy callers
)
from yumi.core.features.memory.models import (
    LONG_TERM_TABLE,
    SESSION_SUMMARY_TABLE,
    TOOL_OBSERVATION_TABLE,
)
from yumi.core.features.memory.repos import (
    LongTermMemoryRepository,
    MessageRepository,
    SessionRepository,
    SessionSummaryRepository,
    ToolObservationRepository,
)
from yumi.core.features.memory.tool_replay import persist_openai_messages as _tool_replay_persist
from yumi.core.features.prompts.store import get_effective_system_prompt
from yumi.logging_config import get_logger

logger = get_logger(__name__)


# Forensic helpers re-exported for external callers (writer.py / context.py).
# They remain procedural; the actual implementations live in ``transcript``.


def _assistant_tool_call_count_from_stored_raw(raw: str) -> int | None:
    return _transcript.assistant_tool_call_count_from_stored_raw(raw)


def _trim_trailing_incomplete_tool_rows(rows: list[dict]) -> list[dict]:
    return _transcript.trim_trailing_incomplete_tool_rows(rows)


def _trim_leading_orphan_tool_rows(rows: list[dict]) -> list[dict]:
    return _transcript.trim_leading_orphan_tool_rows(rows)


def _trim_leading_orphan_assistant_tool_calls(rows: list[dict]) -> list[dict]:
    return _transcript.trim_leading_orphan_assistant_tool_calls(rows)


def _dedupe_consecutive_user_rows(rows: list[dict]) -> list[dict]:
    return _transcript.dedupe_consecutive_user_rows(rows)


class Memory:
    """Façade over the LanceDB backend + repositories.

    The ``Memory`` instance is *cheap* to construct against an already-known
    ``db_dir``: the backend reuses one cached LanceDB connection per directory,
    schema migrations run once per process, and re-embedding starts a daemon
    thread (best-effort). External code should treat this object as a thin
    handle and not assume any heavy state on it.
    """

    def __init__(self, session_id: str = "default", system_prompt=None, storage_dir=None, max_recent: int = 10):
        self.db_dir = storage_dir if storage_dir else str(migrate_legacy_memory_dir())
        self.session_id = session_id
        self.max_recent = max_recent
        # ``system_prompt`` is intentionally ignored — callers persist via
        # ``yumi.core.features.prompts.set_session_prompt``. The argument stays so the
        # historical signature is preserved.

        config = load_model_config()

        # Substrate / collaborators.
        self.backend = LanceDBBackend(self.db_dir)
        self.db = self.backend.db
        self.embedding = EmbeddingProcessor(self.backend, config.embedding_model, get_embed_provider())

        # Table names retained as attributes for legacy callers that reach in.
        self.table_name = MessageRepository.TABLE_NAME
        self.session_table_name = SessionRepository.TABLE_NAME
        self.long_term_table_name = LONG_TERM_TABLE
        self.tool_observation_table_name = TOOL_OBSERVATION_TABLE
        self.session_summary_table_name = SESSION_SUMMARY_TABLE

        # Repositories.
        self.messages = MessageRepository(self.backend, self.embedding, self.session_id)
        self.sessions_repo = SessionRepository(self.backend, self.messages)
        self.messages.bind_sessions(self.sessions_repo)
        self.long_term = LongTermMemoryRepository(self.backend, self.embedding, self.session_id)
        self.tool_observations = ToolObservationRepository(self.backend, self.embedding, self.session_id)
        self.summaries = SessionSummaryRepository(self.backend, self.embedding, self.session_id)

        # One-shot per-process schema init + dim migration.
        if self.backend.claim_initialization():
            self._init_tables()
            self.embedding.maybe_migrate(self.table_name)

    # ── lifecycle / init delegation ────────────────────────────────────────

    def _init_tables(self) -> None:
        self.messages.init_table()
        self.sessions_repo.init_table()

    # ── shims still consumed by external collaborators ─────────────────────
    #
    # ``context.py`` / ``storage.py`` / ``retrieval.py`` reach into Memory via
    # a small set of underscore helpers + the ``embed_model`` property; only
    # those are kept. The ``_list_table_names`` / ``_has_table`` pair must
    # stay safe to call when ``__init__`` was bypassed via
    # ``object.__new__(Memory)`` (used by isolated table-listing tests).

    @property
    def embed_model(self) -> str | None:
        return self.embedding.embed_model

    @embed_model.setter
    def embed_model(self, value: str | None) -> None:
        self.embedding.embed_model = value

    def _list_table_names(self, db=None) -> set[str]:
        target_db = db or self.db
        list_tables = getattr(target_db, "list_tables", None)
        if callable(list_tables):
            result = list_tables()
            names = getattr(result, "tables", result)
            return {str(name) for name in names}
        return {str(name) for name in target_db.table_names()}

    def _has_table(self, table_name: str, db=None) -> bool:
        return table_name in self._list_table_names(db)

    def _table_exists(self) -> bool:
        return self._has_table(self.table_name)

    def _open_table(self):
        return self.db.open_table(self.table_name)

    def _session_table_exists(self) -> bool:
        return self._has_table(self.session_table_name)

    def _build_where_clause(self, field: str, value: str) -> str:
        return self.backend.build_where_clause(field, value)

    def _current_timestamp_num(self) -> int:
        return self.backend.current_timestamp_num()

    # ── public API: messages ───────────────────────────────────────────────

    def add_message(self, role: str, content: str, thought: str | None = None) -> str:
        # Route through ``create_message`` (not the repo's ``add``) so the
        # ``MemoryWriter`` structured-extraction hook fires for every write.
        timestamp = self.backend.format_timestamp()
        timestamp_num = self.backend.current_timestamp_num()
        return self.create_message(
            session_id=self.session_id,
            role=role,
            content=content,
            thought=thought,
            timestamp=timestamp,
            timestamp_num=timestamp_num,
        )["id"]

    def persist_openai_messages(self, messages: list[dict]) -> None:
        """Persist assistant+tool_calls and tool rows so ``get_context`` can replay them."""
        _tool_replay_persist(self, messages)
        try:
            from yumi.core.features.memory.writer import MemoryWriter

            MemoryWriter(self).observe_tool_turns(messages)
        except Exception as exc:
            logger.debug("Structured tool observation write skipped: %s", exc)

    def get_context(
        self,
        query: str | None = None,
        max_cross_session: int | None = None,
        peer_session_ids: list[str] | None = None,
    ):
        from yumi.core.features.memory.context import ContextBuilder

        return ContextBuilder(self).build(
            query=query,
            max_cross_session=max_cross_session,
            peer_session_ids=peer_session_ids,
        )

    def recent_messages_in_sessions(self, session_ids: list[str], limit: int) -> list[dict]:
        return self.messages.recent_messages_in_sessions(session_ids, limit)

    def get_recent_messages(self):
        context = self.get_context()
        return context[1:]

    def search_memory(self, query: str, limit: int = 5):
        return self.search_messages(query=query, session_id=self.session_id, limit=limit)

    def clear_history(self) -> None:
        self.messages.clear_session(self.session_id)

    def delete_message(self, message_id: str) -> bool:
        return self.messages.delete(message_id)

    def list_messages(
        self,
        session_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        include_deleted_sessions: bool = True,
    ):
        deleted_session_ids: set[str] | None = None
        if not include_deleted_sessions and session_id is None:
            deleted_session_ids = {
                session["session_id"] for session in self.list_sessions(status=DELETED_SESSION_STATUS)
            }
        return self.messages.list(
            session_id=session_id,
            limit=limit,
            offset=offset,
            include_deleted_sessions=include_deleted_sessions,
            deleted_session_ids=deleted_session_ids,
        )

    def get_message(self, message_id: str):
        return self.messages.get(message_id)

    def create_message(
        self,
        session_id: str,
        role: str,
        content: str,
        timestamp: str | None = None,
        timestamp_num: int | None = None,
        message_id: str | None = None,
        thought: str | None = None,
    ) -> dict:
        result = self.messages.create(
            session_id=session_id,
            role=role,
            content=content,
            timestamp=timestamp,
            timestamp_num=timestamp_num,
            message_id=message_id,
            thought=thought,
        )
        # Structured-memory write hook is best-effort; runs after the commit.
        try:
            from yumi.core.features.memory.writer import MemoryWriter

            MemoryWriter(self).observe_message(result)
        except Exception as exc:
            logger.debug("Structured memory write skipped: %s", exc)
        return result

    def update_message(self, message_id: str, content: str, role: str | None = None):
        # Mirror legacy: delete + create through ``create_message`` so the
        # ``MemoryWriter`` extractor sees the new content.
        existing = self.get_message(message_id)
        if existing is None:
            return None
        normalized_content = content.strip()
        if not normalized_content:
            raise ValueError("Memory content cannot be empty.")
        updated_role = role.strip().lower() if role is not None else existing["role"]
        if updated_role not in {"system", "user", "assistant", "tool"}:
            raise ValueError("Memory role must be one of: system, user, assistant, tool.")
        self.delete_message(message_id)
        return self.create_message(
            session_id=existing["session_id"],
            role=updated_role,
            content=normalized_content,
            timestamp=self.backend.format_timestamp(),
            timestamp_num=self.backend.current_timestamp_num(),
            message_id=existing["id"],
            thought=existing.get("thought") or None,
        )

    def search_messages(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 5,
        include_deleted_sessions: bool = True,
    ):
        deleted_session_ids: set[str] | None = None
        if not include_deleted_sessions and session_id is None:
            deleted_session_ids = {
                session["session_id"] for session in self.list_sessions(status=DELETED_SESSION_STATUS)
            }
        return self.messages.search(
            query,
            session_id=session_id,
            limit=limit,
            include_deleted_sessions=include_deleted_sessions,
            deleted_session_ids=deleted_session_ids,
        )

    def build_related_memory_message(self, query: str, exclude_session_id: str | None = None, limit: int = 5):
        if not query or not query.strip():
            return None
        related = self.search_messages(query=query, session_id=None, limit=limit)
        seen: set[tuple] = set()
        lines = ["Relevant memory from previous chats:"]
        for item in related:
            if exclude_session_id and item["session_id"] == exclude_session_id:
                continue
            normalized_content = " ".join(item["content"].split())
            dedupe_key = (item["session_id"], item["role"], normalized_content.lower())
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            lines.append(f"- [{item['session_id']}] ({item['role']}, {item['timestamp']}) {normalized_content[:240]}")
        if len(lines) == 1:
            return None
        return {"role": "system", "content": "\n".join(lines)}

    # ── public API: sessions ───────────────────────────────────────────────

    def create_session(self, title: str | None = None, session_id: str | None = None):
        return self.sessions_repo.create(title=title, session_id=session_id)

    def get_session(self, session_id: str):
        return self.sessions_repo.get(session_id)

    def update_session(
        self,
        session_id: str,
        title: str | None = None,
        is_pinned: bool | None = None,
        status: str | None = None,
    ):
        return self.sessions_repo.update(session_id, title=title, is_pinned=is_pinned, status=status)

    def list_sessions(self, status: str = "active", session_id_prefix: str | None = None):
        return self.sessions_repo.list(status=status, session_id_prefix=session_id_prefix)

    # ── public API: long-term memory / tool observations / summaries ──────

    def create_long_term_memory(
        self,
        *,
        kind: str,
        content: str,
        session_id: str | None = None,
        source_message_ids: list[str] | None = None,
        confidence: float = 0.5,
        importance: float = 0.5,
    ):
        return self.long_term.create(
            kind=kind,
            content=content,
            session_id=session_id,
            source_message_ids=source_message_ids,
            confidence=confidence,
            importance=importance,
        )

    def list_long_term_memories(self, kind: str | None = None, session_id: str | None = None, limit: int = 50):
        return self.long_term.list(kind=kind, session_id=session_id, limit=limit)

    def create_tool_observation(
        self,
        *,
        tool_name: str,
        args_summary: str = "",
        result_summary: str,
        success: bool = True,
        session_id: str | None = None,
        call_id: str = "",
        importance: float = 0.5,
    ):
        return self.tool_observations.create(
            tool_name=tool_name,
            args_summary=args_summary,
            result_summary=result_summary,
            success=success,
            session_id=session_id,
            call_id=call_id,
            importance=importance,
        )

    def list_tool_observations(self, session_id: str | None = None, limit: int = 50):
        return self.tool_observations.list(session_id=session_id, limit=limit)

    def get_session_summary(self, session_id: str | None = None):
        return self.summaries.get(session_id=session_id)

    def update_session_summary(
        self,
        summary: str,
        session_id: str | None = None,
        *,
        covered_until_num: int | None = None,
    ):
        return self.summaries.update(summary, session_id=session_id, covered_until_num=covered_until_num)

    # ── prompt accessor ────────────────────────────────────────────────────

    def _current_system_prompt(self) -> str:
        return get_effective_system_prompt(self.session_id)

    def get_system_message(self) -> dict:
        return {"role": "system", "content": self._current_system_prompt()}

    # ── structured-table search (used by retrieval) ────────────────────────

    def _search_structured_table(
        self,
        table_name: str,
        query: str,
        *,
        limit: int = 8,
        content_field: str = "content",
    ) -> list[dict]:
        from yumi.core.features.memory.repos.long_term import _BackendAdapter
        from yumi.core.features.memory.storage import query_rows

        if not self.backend.has_table(table_name):
            return []
        normalized_query = (query or "").strip()
        if not normalized_query:
            return []

        query_vector = self.embedding.get_vector(normalized_query)
        rows: list[dict]
        if (
            self.embedding.embed_model
            and self.embedding.embedding_available
            and not _is_degenerate_vector(query_vector)
        ):
            try:
                rows = self.backend.open_table(table_name).search(query_vector).limit(limit).to_list()
            except Exception as exc:
                logger.debug("Structured vector search failed for %s: %s", table_name, exc)
                rows = []
        else:
            rows = []

        if rows:
            return rows

        lowered = normalized_query.lower()
        # Scope the lexical fallback to the current session so memories from
        # unrelated chats don't bleed into this turn's prompt.
        session_clause = self.backend.build_where_clause("session_id", self.session_id) if self.session_id else None
        all_rows = query_rows(
            _BackendAdapter(self.backend),
            table_name,
            ordering_field_name=(
                "updated_at_num" if table_name != self.tool_observation_table_name else "timestamp_num"
            ),
            where_clause=session_clause,
        )
        from yumi.core.features.memory.retrieval import keyword_score

        matches = [
            row
            for row in all_rows
            if lowered in str(row.get(content_field, "")).lower()
            or keyword_score(normalized_query, str(row.get(content_field, ""))) > 0
        ]
        matches.sort(
            key=lambda row: int(
                row.get("updated_at_num") or row.get("timestamp_num") or row.get("created_at_num") or 0
            ),
            reverse=True,
        )
        return matches[:limit]


__all__ = ["Memory"]
