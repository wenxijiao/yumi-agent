"""SQLite-backed canonical storage.

SQLite is the source of truth for durable, editable state. LanceDB remains a
derived vector index and can be rebuilt from these tables.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = 1
DEFAULT_CONFIG_DIR = Path.home() / ".yumi"
YUMI_V1_TOOL_CALLS = "__yumi:v1:tc__\n"
YUMI_V1_TOOL_RESULT = "__yumi:v1:tool__\n"
DEFAULT_SESSION_TITLE = "New chat"
ACTIVE_SESSION_STATUS = "active"

SECRET_FIELDS = frozenset(
    {
        "openai_api_key",
        "gemini_api_key",
        "claude_api_key",
        "deepseek_api_key",
        "grok_api_key",
        "tts_api_key",
        "telegram_bot_token",
        "discord_bot_token",
        "line_channel_secret",
        "line_channel_access_token",
        "lan_secret",
        "connection_code",
        "voice_porcupine_access_key",
    }
)

MODEL_PROFILE_COLUMNS = (
    "chat_provider",
    "chat_model",
    "embedding_provider",
    "embedding_model",
    "embedding_dim",
    "stt_provider",
    "stt_backend",
    "stt_model",
    "stt_model_dir",
    "stt_language",
    "tts_provider",
    "tts_voice",
    "tts_model",
    "tts_language",
    "openai_base_url",
    "deepseek_base_url",
    "grok_base_url",
)
MODEL_PROFILE_FIELDS = frozenset(MODEL_PROFILE_COLUMNS)

PROMPT_FIELDS = frozenset({"system_prompt", "session_prompts", "proactive_profile_prompt"})
TOOL_POLICY_FIELDS = frozenset({"local_tools_always_allow", "local_tools_force_confirm"})
MEMORY_EVENT_TYPES = frozenset(
    {
        "user_message",
        "assistant_message",
        "assistant_tool_calls",
        "tool_result",
        "system_note",
    }
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_loads(raw: str | None, default: Any = None) -> Any:
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return default


def db_path_for_config_path(config_path: str | Path) -> Path:
    """Return the app DB next to the active config path."""

    return Path(config_path).expanduser().resolve().with_name("yumi.db")


def default_db_path() -> Path:
    return DEFAULT_CONFIG_DIR / "yumi.db"


def db_path_for_memory_storage(storage_dir: str | Path | None) -> Path:
    """Return the canonical DB path for a memory store.

    The default single-user memory dir is ``~/.yumi/memory`` and maps to
    ``~/.yumi/yumi.db``. Test-created arbitrary temp storage dirs keep their DB
    inside the temp dir so tests do not touch the user's real DB.
    """

    if storage_dir is None:
        return DEFAULT_CONFIG_DIR / "yumi.db"
    p = Path(storage_dir).expanduser().resolve()
    if p.name == "memory":
        return p.parent / "yumi.db"
    return p / "yumi.db"


class SQLiteStore:
    """Small SQLite repository for Yumi's canonical local state."""

    _schema_lock = threading.Lock()
    _initialized: set[Path] = set()

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.ensure_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def ensure_schema(self) -> None:
        with SQLiteStore._schema_lock:
            if self.db_path in SQLiteStore._initialized and self.db_path.exists():
                return
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            with self.connect() as conn:
                for statement in _SCHEMA_SQL:
                    conn.execute(statement)
                conn.execute(
                    """
                    INSERT INTO db_meta(key, value_json, updated_at)
                    VALUES('schema_version', ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                      value_json=excluded.value_json,
                      updated_at=excluded.updated_at
                    """,
                    (_json(SCHEMA_VERSION), _utc_now()),
                )
            try:
                self.db_path.chmod(0o600)
            except OSError:
                pass
            SQLiteStore._initialized.add(self.db_path)

    # ------------------------------------------------------------------
    # Config / prompts / secrets

    def has_model_config(self) -> bool:
        with self.connect() as conn:
            row = conn.execute("SELECT 1 FROM model_profiles WHERE id='default' LIMIT 1").fetchone()
            if row:
                return True
            row = conn.execute("SELECT 1 FROM settings WHERE namespace='model_config' LIMIT 1").fetchone()
            return row is not None

    def load_model_config_dict(self) -> dict[str, Any] | None:
        if not self.has_model_config():
            return None
        data: dict[str, Any] = {}
        with self.connect() as conn:
            for row in conn.execute("SELECT key, value_json FROM settings WHERE namespace='model_config'"):
                data[str(row["key"])] = _json_loads(row["value_json"])

            profile = conn.execute("SELECT * FROM model_profiles WHERE id='default'").fetchone()
            if profile is not None:
                for field in MODEL_PROFILE_COLUMNS:
                    if field in profile.keys():
                        data[field] = profile[field]
                options = _json_loads(profile["options_json"], {}) or {}
                if isinstance(options, dict):
                    data.update(options)

            for row in conn.execute("SELECT name, encrypted_value FROM secrets"):
                data[str(row["name"])] = row["encrypted_value"]

            global_prompt = conn.execute(
                "SELECT content FROM prompts WHERE scope='global' AND session_id='' AND deleted_at IS NULL"
            ).fetchone()
            if global_prompt is not None:
                data["system_prompt"] = global_prompt["content"]

            session_prompts: dict[str, str] = {}
            for row in conn.execute(
                "SELECT session_id, content FROM prompts WHERE scope='session' AND deleted_at IS NULL"
            ):
                sid = row["session_id"]
                if sid:
                    session_prompts[str(sid)] = row["content"]
            if session_prompts:
                data["session_prompts"] = session_prompts

            proactive = conn.execute(
                "SELECT content FROM prompts WHERE scope='proactive' AND session_id='' AND deleted_at IS NULL"
            ).fetchone()
            if proactive is not None:
                data["proactive_profile_prompt"] = proactive["content"]

            always = [
                row["tool_name"]
                for row in conn.execute(
                    "SELECT tool_name FROM tool_policies WHERE always_allow=1 ORDER BY tool_name"
                )
            ]
            force = [
                row["tool_name"]
                for row in conn.execute(
                    "SELECT tool_name FROM tool_policies WHERE require_confirmation=1 ORDER BY tool_name"
                )
            ]
            if always:
                data["local_tools_always_allow"] = always
            if force:
                data["local_tools_force_confirm"] = force
        return data

    def save_model_config_dict(self, data: dict[str, Any]) -> None:
        now = _utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO model_profiles(
                  id, name, is_active,
                  chat_provider, chat_model,
                  embedding_provider, embedding_model, embedding_dim,
                  stt_provider, stt_backend, stt_model, stt_model_dir, stt_language,
                  tts_provider, tts_voice, tts_model, tts_language,
                  openai_base_url, deepseek_base_url, grok_base_url,
                  options_json, created_at, updated_at
                ) VALUES(
                  'default', 'Default', 1,
                  ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?
                )
                ON CONFLICT(id) DO UPDATE SET
                  is_active=1,
                  chat_provider=excluded.chat_provider,
                  chat_model=excluded.chat_model,
                  embedding_provider=excluded.embedding_provider,
                  embedding_model=excluded.embedding_model,
                  embedding_dim=excluded.embedding_dim,
                  stt_provider=excluded.stt_provider,
                  stt_backend=excluded.stt_backend,
                  stt_model=excluded.stt_model,
                  stt_model_dir=excluded.stt_model_dir,
                  stt_language=excluded.stt_language,
                  tts_provider=excluded.tts_provider,
                  tts_voice=excluded.tts_voice,
                  tts_model=excluded.tts_model,
                  tts_language=excluded.tts_language,
                  openai_base_url=excluded.openai_base_url,
                  deepseek_base_url=excluded.deepseek_base_url,
                  grok_base_url=excluded.grok_base_url,
                  updated_at=excluded.updated_at
                """,
                tuple(data.get(k) for k in MODEL_PROFILE_COLUMNS)
                + (
                    now,
                    now,
                ),
            )

            conn.execute("DELETE FROM settings WHERE namespace='model_config'")
            for key, value in data.items():
                if key in MODEL_PROFILE_FIELDS or key in SECRET_FIELDS or key in PROMPT_FIELDS or key in TOOL_POLICY_FIELDS:
                    continue
                conn.execute(
                    """
                    INSERT INTO settings(namespace, key, value_json, updated_at)
                    VALUES('model_config', ?, ?, ?)
                    ON CONFLICT(namespace, key) DO UPDATE SET
                      value_json=excluded.value_json,
                      updated_at=excluded.updated_at
                    """,
                    (key, _json(value), now),
                )

            for name in SECRET_FIELDS:
                value = data.get(name)
                if value is None or (isinstance(value, str) and not value.strip()):
                    conn.execute("DELETE FROM secrets WHERE name=?", (name,))
                    continue
                text = str(value)
                conn.execute(
                    """
                    INSERT INTO secrets(name, provider, secret_type, encrypted_value, last4, encryption_scheme, updated_at)
                    VALUES(?, ?, ?, ?, ?, 'plain', ?)
                    ON CONFLICT(name) DO UPDATE SET
                      provider=excluded.provider,
                      secret_type=excluded.secret_type,
                      encrypted_value=excluded.encrypted_value,
                      last4=excluded.last4,
                      encryption_scheme=excluded.encryption_scheme,
                      updated_at=excluded.updated_at
                    """,
                    (name, _provider_for_secret(name), _secret_type_for_name(name), text, text[-4:], now),
                )

            conn.execute("UPDATE prompts SET deleted_at=? WHERE scope IN ('global', 'session', 'proactive')", (now,))
            system_prompt = data.get("system_prompt")
            if isinstance(system_prompt, str) and system_prompt.strip():
                self._put_prompt(conn, "global", None, system_prompt.strip(), now)
            session_prompts = data.get("session_prompts") or {}
            if isinstance(session_prompts, dict):
                for session_id, content in session_prompts.items():
                    if isinstance(content, str):
                        self._put_prompt(conn, "session", str(session_id), content.strip(), now)
            proactive_prompt = data.get("proactive_profile_prompt")
            if isinstance(proactive_prompt, str) and proactive_prompt.strip():
                self._put_prompt(conn, "proactive", None, proactive_prompt.strip(), now)

            conn.execute("DELETE FROM tool_policies")
            always_allow = set(_string_list(data.get("local_tools_always_allow")))
            force_confirm = set(_string_list(data.get("local_tools_force_confirm")))
            for tool_name in sorted(always_allow | force_confirm):
                conn.execute(
                    """
                    INSERT INTO tool_policies(tool_name, disabled, require_confirmation, always_allow, metadata_json, updated_at)
                    VALUES(?, 0, ?, ?, '{}', ?)
                    """,
                    (tool_name, 1 if tool_name in force_confirm else 0, 1 if tool_name in always_allow else 0, now),
                )

    def _put_prompt(
        self,
        conn: sqlite3.Connection,
        scope: str,
        session_id: str | None,
        content: str,
        now: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO prompts(id, scope, session_id, content, revision, created_at, updated_at, deleted_at)
            VALUES(?, ?, ?, ?, 1, ?, ?, NULL)
            ON CONFLICT(scope, session_id) DO UPDATE SET
              content=excluded.content,
              revision=prompts.revision + 1,
              updated_at=excluded.updated_at,
              deleted_at=NULL
            """,
            (str(uuid.uuid4()), scope, session_id or "", content, now, now),
        )

    # ------------------------------------------------------------------
    # Sessions and canonical events

    def event_count(self, session_id: str | None = None) -> int:
        with self.connect() as conn:
            if session_id is None:
                row = conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) AS n FROM events WHERE session_id=?", (session_id,)).fetchone()
            return int(row["n"] if row else 0)

    # ------------------------------------------------------------------
    # Token usage (analytics for the stats dashboard)

    def record_token_usage(
        self,
        *,
        session_id: str,
        turn_id: str = "",
        owner_user_id: str = "",
        provider: str = "",
        model: str = "",
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> dict[str, Any]:
        """Persist one row of token usage for a completed assistant turn."""
        prompt = max(0, int(prompt_tokens or 0))
        completion = max(0, int(completion_tokens or 0))
        total = prompt + completion
        now = _utc_now()
        now_num = int(datetime.now(timezone.utc).timestamp() * 1000)
        row = {
            "id": uuid.uuid4().hex,
            "session_id": session_id or "",
            "turn_id": turn_id or "",
            "owner_user_id": owner_user_id or "",
            "provider": provider or "",
            "model": model or "",
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": total,
            "created_at": now,
            "created_at_num": now_num,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO token_usage(
                  id, session_id, turn_id, owner_user_id, provider, model,
                  prompt_tokens, completion_tokens, total_tokens, created_at, created_at_num
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["session_id"],
                    row["turn_id"],
                    row["owner_user_id"],
                    row["provider"],
                    row["model"],
                    prompt,
                    completion,
                    total,
                    now,
                    now_num,
                ),
            )
        return row

    def token_usage_summary(self, *, session_id: str | None = None) -> dict[str, Any]:
        """Totals + per-model breakdown across all (or one session's) turns."""
        where = "WHERE session_id=?" if session_id else ""
        params: tuple[Any, ...] = (session_id,) if session_id else ()
        with self.connect() as conn:
            totals = conn.execute(
                f"""
                SELECT COUNT(*) AS turns,
                       COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                       COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                       COALESCE(SUM(total_tokens), 0) AS total_tokens
                FROM token_usage {where}
                """,
                params,
            ).fetchone()
            by_model = conn.execute(
                f"""
                SELECT CASE WHEN model='' THEN 'unknown' ELSE model END AS model,
                       COUNT(*) AS turns,
                       COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                       COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                       COALESCE(SUM(total_tokens), 0) AS total_tokens
                FROM token_usage {where}
                GROUP BY model
                ORDER BY total_tokens DESC
                """,
                params,
            ).fetchall()
        return {
            "turns": int(totals["turns"] or 0) if totals else 0,
            "prompt_tokens": int(totals["prompt_tokens"] or 0) if totals else 0,
            "completion_tokens": int(totals["completion_tokens"] or 0) if totals else 0,
            "total_tokens": int(totals["total_tokens"] or 0) if totals else 0,
            "by_model": [
                {
                    "model": r["model"],
                    "turns": int(r["turns"] or 0),
                    "prompt_tokens": int(r["prompt_tokens"] or 0),
                    "completion_tokens": int(r["completion_tokens"] or 0),
                    "total_tokens": int(r["total_tokens"] or 0),
                }
                for r in by_model
            ],
        }

    def token_usage_timeseries(self, *, days: int = 14) -> list[dict[str, Any]]:
        """Per-day token totals for the most recent *days* (UTC, oldest first)."""
        limit = max(1, min(120, int(days)))
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT substr(created_at, 1, 10) AS day,
                       COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                       COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                       COALESCE(SUM(total_tokens), 0) AS total_tokens,
                       COUNT(*) AS turns
                FROM token_usage
                GROUP BY day
                ORDER BY day DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        out = [
            {
                "day": r["day"],
                "prompt_tokens": int(r["prompt_tokens"] or 0),
                "completion_tokens": int(r["completion_tokens"] or 0),
                "total_tokens": int(r["total_tokens"] or 0),
                "turns": int(r["turns"] or 0),
            }
            for r in rows
        ]
        out.reverse()
        return out

    def session_turn_counts(self) -> dict[str, int]:
        """Assistant-message count per session — a proxy for conversation turns."""
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT session_id, COUNT(*) AS n
                FROM events
                WHERE event_type='assistant_message' AND deleted_at IS NULL
                GROUP BY session_id
                """
            ).fetchall()
        return {r["session_id"]: int(r["n"] or 0) for r in rows}

    def import_messages(self, rows: list[dict[str, Any]]) -> None:
        for row in sorted(rows, key=lambda r: int(r.get("timestamp_num") or 0)):
            self.upsert_event_from_message(row, create_job=False)

    def upsert_event_from_message(self, message: dict[str, Any], *, create_job: bool = True) -> None:
        parsed = _event_fields_from_message(message)
        now = _utc_now()
        with self.connect() as conn:
            existing = conn.execute("SELECT revision FROM events WHERE id=?", (parsed["id"],)).fetchone()
            revision = int(existing["revision"] if existing else 0) + (1 if existing else 0)
            conn.execute(
                """
                INSERT INTO events(
                  id, session_id, turn_id, event_type, role, content, thought,
                  tool_call_id, tool_name, tool_args_json, tool_calls_json,
                  metadata_json, revision, timestamp, timestamp_num,
                  created_at, updated_at, deleted_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                ON CONFLICT(id) DO UPDATE SET
                  session_id=excluded.session_id,
                  turn_id=excluded.turn_id,
                  event_type=excluded.event_type,
                  role=excluded.role,
                  content=excluded.content,
                  thought=excluded.thought,
                  tool_call_id=excluded.tool_call_id,
                  tool_name=excluded.tool_name,
                  tool_args_json=excluded.tool_args_json,
                  tool_calls_json=excluded.tool_calls_json,
                  metadata_json=excluded.metadata_json,
                  revision=events.revision + 1,
                  timestamp=excluded.timestamp,
                  timestamp_num=excluded.timestamp_num,
                  updated_at=excluded.updated_at,
                  deleted_at=NULL
                """,
                (
                    parsed["id"],
                    parsed["session_id"],
                    parsed["turn_id"],
                    parsed["event_type"],
                    parsed["role"],
                    parsed["content"],
                    parsed["thought"],
                    parsed["tool_call_id"],
                    parsed["tool_name"],
                    parsed["tool_args_json"],
                    parsed["tool_calls_json"],
                    parsed["metadata_json"],
                    revision,
                    parsed["timestamp"],
                    parsed["timestamp_num"],
                    now,
                    now,
                ),
            )
            self._refresh_session_stats(conn, parsed["session_id"], now)
            if create_job and parsed["event_type"] in MEMORY_EVENT_TYPES:
                self._enqueue_embedding_job(conn, "event", parsed["id"], "upsert", revision, now)

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM events
                WHERE id=? AND deleted_at IS NULL
                """,
                (message_id,),
            ).fetchone()
        return _event_row_to_message(row) if row is not None else None

    def list_messages(
        self,
        *,
        session_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        include_deleted_sessions: bool = True,
    ) -> list[dict[str, Any]]:
        clauses = ["e.deleted_at IS NULL"]
        params: list[Any] = []
        if session_id is not None:
            clauses.append("e.session_id=?")
            params.append(session_id)
        if not include_deleted_sessions:
            clauses.append("COALESCE(s.status, 'active') != 'deleted'")
        where = " AND ".join(clauses)
        params.extend([limit, offset])
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT e.* FROM events e
                LEFT JOIN sessions s ON s.session_id=e.session_id
                WHERE {where}
                ORDER BY e.seq ASC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        return [_event_row_to_message(row) for row in rows]

    def recent_transcript_rows(
        self,
        session_id: str,
        limit: int,
        *,
        peer_session_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        session_ids = [session_id] + list(peer_session_ids or [])
        placeholders = ",".join("?" for _ in session_ids)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM events
                WHERE deleted_at IS NULL
                  AND session_id IN ({placeholders})
                ORDER BY seq DESC
                LIMIT ?
                """,
                [*session_ids, limit],
            ).fetchall()
        out = [_event_row_to_message(row) for row in reversed(rows)]
        return out

    def update_message(
        self,
        message_id: str,
        *,
        role: str | None = None,
        content: str | None = None,
        thought: str | None = None,
    ) -> dict[str, Any] | None:
        existing = self.get_message(message_id)
        if existing is None:
            return None
        updated = dict(existing)
        if role is not None:
            updated["role"] = role
        if content is not None:
            updated["content"] = content
        if thought is not None:
            updated["thought"] = thought
        self.upsert_event_from_message(updated)
        return self.get_message(message_id)

    def delete_message(self, message_id: str) -> bool:
        now = _utc_now()
        with self.connect() as conn:
            existing = conn.execute("SELECT session_id, revision FROM events WHERE id=?", (message_id,)).fetchone()
            if existing is None:
                return False
            conn.execute("UPDATE events SET deleted_at=?, updated_at=?, revision=revision+1 WHERE id=?", (now, now, message_id))
            self._refresh_session_stats(conn, existing["session_id"], now)
            self._enqueue_embedding_job(conn, "event", message_id, "delete", int(existing["revision"]) + 1, now)
            return True

    def clear_session(self, session_id: str) -> None:
        now = _utc_now()
        with self.connect() as conn:
            rows = conn.execute("SELECT id, revision FROM events WHERE session_id=? AND deleted_at IS NULL", (session_id,)).fetchall()
            conn.execute("UPDATE events SET deleted_at=?, updated_at=?, revision=revision+1 WHERE session_id=? AND deleted_at IS NULL", (now, now, session_id))
            for row in rows:
                self._enqueue_embedding_job(conn, "event", row["id"], "delete", int(row["revision"]) + 1, now)
            self._refresh_session_stats(conn, session_id, now)

    def upsert_session(self, session: dict[str, Any]) -> None:
        now = _utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions(
                  session_id, owner_user_id, channel, title, status, is_pinned,
                  created_at, created_at_num, updated_at, updated_at_num,
                  last_event_seq, last_message_at, last_message_at_num,
                  message_count, metadata_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                  title=excluded.title,
                  status=excluded.status,
                  is_pinned=excluded.is_pinned,
                  updated_at=excluded.updated_at,
                  updated_at_num=excluded.updated_at_num,
                  last_message_at=excluded.last_message_at,
                  last_message_at_num=excluded.last_message_at_num,
                  message_count=excluded.message_count
                """,
                (
                    session["session_id"],
                    session.get("owner_user_id") or "",
                    session.get("channel") or _channel_from_session_id(session["session_id"]),
                    session.get("title") or DEFAULT_SESSION_TITLE,
                    session.get("status") or ACTIVE_SESSION_STATUS,
                    1 if session.get("is_pinned") else 0,
                    session.get("created_at") or now,
                    int(session.get("created_at_num") or 0),
                    session.get("updated_at") or now,
                    int(session.get("updated_at_num") or 0),
                    int(session.get("last_event_seq") or 0),
                    session.get("last_message_at") or "",
                    int(session.get("last_message_at_num") or 0),
                    int(session.get("message_count") or 0),
                    _json(session.get("metadata") or {}),
                ),
            )

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
        return _session_row(row) if row is not None else None

    def list_sessions(self, *, status: str = ACTIVE_SESSION_STATUS, session_id_prefix: str | None = None) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if status != "all":
            clauses.append("status=?")
            params.append(status)
        if session_id_prefix:
            clauses.append("session_id LIKE ?")
            params.append(f"{session_id_prefix}%")
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM sessions
                {where}
                ORDER BY is_pinned DESC, MAX(last_message_at_num, updated_at_num) DESC
                """,
                params,
            ).fetchall()
        return [_session_row(row) for row in rows]

    def _refresh_session_stats(self, conn: sqlite3.Connection, session_id: str, now: str) -> None:
        row = conn.execute(
            """
            SELECT COUNT(*) AS n, MAX(seq) AS last_seq, MAX(timestamp_num) AS last_num
            FROM events
            WHERE session_id=? AND deleted_at IS NULL
            """,
            (session_id,),
        ).fetchone()
        latest = conn.execute(
            """
            SELECT timestamp, timestamp_num, content, role FROM events
            WHERE session_id=? AND deleted_at IS NULL
            ORDER BY seq DESC LIMIT 1
            """,
            (session_id,),
        ).fetchone()
        title_row = conn.execute(
            """
            SELECT content FROM events
            WHERE session_id=? AND deleted_at IS NULL AND role='user'
            ORDER BY seq ASC LIMIT 1
            """,
            (session_id,),
        ).fetchone()
        title = _derive_title(title_row["content"] if title_row else "")
        conn.execute(
            """
            INSERT INTO sessions(
              session_id, owner_user_id, channel, title, status, is_pinned,
              created_at, created_at_num, updated_at, updated_at_num,
              last_event_seq, last_message_at, last_message_at_num,
              message_count, metadata_json
            ) VALUES(?, '', ?, ?, 'active', 0, ?, ?, ?, ?, ?, ?, ?, ?, '{}')
            ON CONFLICT(session_id) DO UPDATE SET
              title=CASE WHEN sessions.title IS NULL OR sessions.title='' OR sessions.title=? THEN excluded.title ELSE sessions.title END,
              updated_at=excluded.updated_at,
              updated_at_num=excluded.updated_at_num,
              last_event_seq=excluded.last_event_seq,
              last_message_at=excluded.last_message_at,
              last_message_at_num=excluded.last_message_at_num,
              message_count=excluded.message_count
            """,
            (
                session_id,
                _channel_from_session_id(session_id),
                title,
                now,
                int(latest["timestamp_num"] if latest else 0),
                now,
                int(datetime.now(timezone.utc).timestamp() * 1000),
                int(row["last_seq"] or 0),
                latest["timestamp"] if latest else "",
                int(row["last_num"] or 0),
                int(row["n"] or 0),
                DEFAULT_SESSION_TITLE,
            ),
        )

    def _enqueue_embedding_job(
        self,
        conn: sqlite3.Connection,
        target_type: str,
        target_id: str,
        action: str,
        target_revision: int,
        now: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO embedding_jobs(
              id, target_type, target_id, action, embedding_model, target_revision,
              status, attempts, created_at, updated_at
            ) VALUES(?, ?, ?, ?, '', ?, 'pending', 0, ?, ?)
            """,
            (str(uuid.uuid4()), target_type, target_id, action, target_revision, now, now),
        )

    # ------------------------------------------------------------------
    # Structured memory mirrors

    def upsert_memory(self, row: dict[str, Any]) -> None:
        now = _utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO memories(
                  id, kind, content, source_event_ids_json, confidence, importance,
                  session_id, metadata_json, revision, created_at, updated_at, deleted_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, NULL)
                ON CONFLICT(id) DO UPDATE SET
                  kind=excluded.kind,
                  content=excluded.content,
                  source_event_ids_json=excluded.source_event_ids_json,
                  confidence=excluded.confidence,
                  importance=excluded.importance,
                  session_id=excluded.session_id,
                  metadata_json=excluded.metadata_json,
                  revision=memories.revision+1,
                  updated_at=excluded.updated_at,
                  deleted_at=NULL
                """,
                (
                    row["id"],
                    row.get("kind") or "fact",
                    row.get("content") or row.get("result_summary") or "",
                    _json(row.get("source_message_ids") or row.get("source_event_ids") or []),
                    float(row.get("confidence") or 0.5),
                    float(row.get("importance") or 0.5),
                    row.get("session_id") or "",
                    _json(row.get("metadata") or {}),
                    now,
                    now,
                ),
            )
            self._enqueue_embedding_job(conn, "memory", row["id"], "upsert", int(row.get("revision") or 1), now)

    def upsert_session_summary(self, row: dict[str, Any]) -> None:
        now = _utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO session_summaries(
                  session_id, summary, covered_until_seq, revision, created_at, updated_at
                ) VALUES(?, ?, ?, 1, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                  summary=excluded.summary,
                  covered_until_seq=excluded.covered_until_seq,
                  revision=session_summaries.revision+1,
                  updated_at=excluded.updated_at
                """,
                (
                    row.get("session_id") or "",
                    row.get("summary") or "",
                    int(row.get("covered_until_seq") or row.get("covered_until_num") or 0),
                    now,
                    now,
                ),
            )

    def record_file(
        self,
        *,
        session_id: str,
        original_name: str,
        path: str,
        size_bytes: int,
        mime_type: str = "",
        sha256: str = "",
        event_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = _utc_now()
        file_id = str(uuid.uuid4())
        row = {
            "id": file_id,
            "session_id": session_id,
            "event_id": event_id,
            "original_name": original_name,
            "path": path,
            "mime_type": mime_type,
            "size_bytes": int(size_bytes or 0),
            "sha256": sha256,
            "metadata_json": _json(metadata or {}),
            "created_at": now,
        }
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO files(
                  id, session_id, event_id, original_name, path, mime_type,
                  size_bytes, sha256, metadata_json, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["session_id"],
                    row["event_id"],
                    row["original_name"],
                    row["path"],
                    row["mime_type"],
                    row["size_bytes"],
                    row["sha256"],
                    row["metadata_json"],
                    row["created_at"],
                ),
            )
        return row

    def save_schedules(self, items: list[dict[str, Any]]) -> None:
        now = _utc_now()
        with self.connect() as conn:
            conn.execute("DELETE FROM schedules")
            for item in items:
                schedule_id = str(item.get("id") or uuid.uuid4().hex[:8])
                conn.execute(
                    """
                    INSERT INTO schedules(
                      id, session_id, schedule_type, payload_json, next_fire_at,
                      status, created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        schedule_id,
                        str(item.get("session_id") or ""),
                        str(item.get("type") or "scheduled"),
                        _json(item),
                        str(item.get("next_fire_at") or item.get("fire_at") or ""),
                        str(item.get("status") or "active"),
                        str(item.get("created_at") or now),
                        now,
                    ),
                )

    def load_schedules(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM schedules WHERE status='active' ORDER BY next_fire_at"
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            value = _json_loads(row["payload_json"], {})
            if isinstance(value, dict):
                out.append(value)
        return out

    def load_proactive_state(self) -> dict[str, Any]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT key, value_json FROM settings WHERE namespace='proactive_state'"
            ).fetchall()
        return {str(row["key"]): _json_loads(row["value_json"], {}) for row in rows}

    def save_proactive_state(self, data: dict[str, Any]) -> None:
        now = _utc_now()
        with self.connect() as conn:
            conn.execute("DELETE FROM settings WHERE namespace='proactive_state'")
            for key, value in data.items():
                conn.execute(
                    """
                    INSERT INTO settings(namespace, key, value_json, updated_at)
                    VALUES('proactive_state', ?, ?, ?)
                    """,
                    (str(key), _json(value), now),
                )

    def clear_memory_tables(self) -> None:
        now = _utc_now()
        with self.connect() as conn:
            for table in (
                "events",
                "memories",
                "session_summaries",
                "embedding_jobs",
                "vector_index_records",
                "files",
                "schedules",
            ):
                conn.execute(f"DELETE FROM {table}")
            conn.execute(
                "INSERT INTO audit_log(id, actor, action, target_type, created_at) VALUES(?, 'system', 'cleanup_memory', 'sqlite', ?)",
                (str(uuid.uuid4()), now),
            )


def _provider_for_secret(name: str) -> str:
    for prefix in ("openai", "gemini", "claude", "deepseek", "grok", "telegram", "discord", "line", "tts"):
        if name.startswith(prefix):
            return prefix
    return "yumi"


def _secret_type_for_name(name: str) -> str:
    if "token" in name:
        return "token"
    if "secret" in name:
        return "secret"
    if "connection_code" in name:
        return "connection_code"
    return "api_key"


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _event_fields_from_message(message: dict[str, Any]) -> dict[str, Any]:
    role = str(message.get("role") or "user").strip().lower()
    raw_content = str(message.get("content") or "")
    content = raw_content
    event_type = f"{role}_message" if role in {"user", "assistant"} else "system_note"
    tool_call_id = ""
    tool_name = ""
    tool_args_json = ""
    tool_calls_json = ""
    metadata: dict[str, Any] = {}

    if role == "assistant" and raw_content.startswith(YUMI_V1_TOOL_CALLS):
        event_type = "assistant_tool_calls"
        payload = _json_loads(raw_content[len(YUMI_V1_TOOL_CALLS) :], {}) or {}
        calls = payload.get("tool_calls") if isinstance(payload, dict) else None
        if isinstance(calls, list):
            tool_calls_json = _json(calls)
            if calls:
                first = calls[0] if isinstance(calls[0], dict) else {}
                tool_call_id = str(first.get("id") or "")
                fn = first.get("function") if isinstance(first.get("function"), dict) else {}
                tool_name = str(fn.get("name") or "")
                tool_args_json = _json(fn.get("arguments") or {})
        if isinstance(payload, dict) and payload.get("reasoning_content"):
            metadata["reasoning_content"] = payload.get("reasoning_content")
    elif role == "tool":
        event_type = "tool_result"
        if raw_content.startswith(YUMI_V1_TOOL_RESULT):
            payload = _json_loads(raw_content[len(YUMI_V1_TOOL_RESULT) :], {}) or {}
            if isinstance(payload, dict):
                tool_name = str(payload.get("name") or "tool")
    elif role == "system":
        event_type = "system_note"

    timestamp_num = int(message.get("timestamp_num") or int(datetime.now(timezone.utc).timestamp() * 1000))
    return {
        "id": str(message.get("id") or uuid.uuid4()),
        "session_id": str(message.get("session_id") or "default"),
        "turn_id": str(message.get("turn_id") or ""),
        "event_type": event_type,
        "role": role,
        "content": content,
        "thought": str(message.get("thought") or ""),
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "tool_args_json": tool_args_json,
        "tool_calls_json": tool_calls_json,
        "metadata_json": _json(metadata),
        "timestamp": str(message.get("timestamp") or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %A")),
        "timestamp_num": timestamp_num,
    }


def _event_row_to_message(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "role": row["role"],
        "content": row["content"],
        "thought": row["thought"] or "",
        "timestamp": row["timestamp"],
        "timestamp_num": int(row["timestamp_num"]),
    }


def _session_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "session_id": row["session_id"],
        "title": row["title"],
        "status": row["status"],
        "is_pinned": bool(row["is_pinned"]),
        "created_at": row["created_at"],
        "created_at_num": int(row["created_at_num"] or 0),
        "updated_at": row["updated_at"],
        "updated_at_num": int(row["updated_at_num"] or 0),
        "last_message_at": row["last_message_at"] or "",
        "last_message_at_num": int(row["last_message_at_num"] or 0),
        "message_count": int(row["message_count"] or 0),
    }


def _derive_title(content: str) -> str:
    title = " ".join(str(content or "").split())
    if not title:
        return DEFAULT_SESSION_TITLE
    return title[:60]


def _channel_from_session_id(session_id: str) -> str:
    for prefix, channel in (("tg_", "telegram"), ("voice_", "voice"), ("chat_", "chat")):
        if session_id.startswith(prefix):
            return channel
    return "chat"


_SCHEMA_SQL = [
    """
    CREATE TABLE IF NOT EXISTS db_meta (
      key TEXT PRIMARY KEY,
      value_json TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS settings (
      namespace TEXT NOT NULL,
      key TEXT NOT NULL,
      value_json TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(namespace, key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS secrets (
      name TEXT PRIMARY KEY,
      provider TEXT NOT NULL DEFAULT '',
      secret_type TEXT NOT NULL DEFAULT '',
      encrypted_value TEXT NOT NULL,
      last4 TEXT NOT NULL DEFAULT '',
      encryption_scheme TEXT NOT NULL DEFAULT 'plain',
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS model_profiles (
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      is_active INTEGER NOT NULL DEFAULT 0,
      chat_provider TEXT NOT NULL DEFAULT 'ollama',
      chat_model TEXT,
      embedding_provider TEXT NOT NULL DEFAULT 'ollama',
      embedding_model TEXT,
      embedding_dim INTEGER,
      stt_provider TEXT NOT NULL DEFAULT 'disabled',
      stt_backend TEXT NOT NULL DEFAULT 'faster-whisper',
      stt_model TEXT,
      stt_model_dir TEXT,
      stt_language TEXT NOT NULL DEFAULT 'auto',
      tts_provider TEXT NOT NULL DEFAULT 'disabled',
      tts_voice TEXT,
      tts_model TEXT,
      tts_language TEXT NOT NULL DEFAULT 'auto',
      openai_base_url TEXT,
      deepseek_base_url TEXT,
      grok_base_url TEXT,
      options_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS prompts (
      id TEXT PRIMARY KEY,
      scope TEXT NOT NULL,
      session_id TEXT NOT NULL DEFAULT '',
      content TEXT NOT NULL,
      revision INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      deleted_at TEXT,
      UNIQUE(scope, session_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tool_policies (
      tool_name TEXT PRIMARY KEY,
      disabled INTEGER NOT NULL DEFAULT 0,
      require_confirmation INTEGER NOT NULL DEFAULT 0,
      always_allow INTEGER NOT NULL DEFAULT 0,
      metadata_json TEXT NOT NULL DEFAULT '{}',
      updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
      session_id TEXT PRIMARY KEY,
      owner_user_id TEXT NOT NULL DEFAULT '',
      channel TEXT NOT NULL DEFAULT 'chat',
      title TEXT NOT NULL DEFAULT 'New chat',
      status TEXT NOT NULL DEFAULT 'active',
      is_pinned INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL,
      created_at_num INTEGER NOT NULL DEFAULT 0,
      updated_at TEXT NOT NULL,
      updated_at_num INTEGER NOT NULL DEFAULT 0,
      last_event_seq INTEGER NOT NULL DEFAULT 0,
      last_message_at TEXT NOT NULL DEFAULT '',
      last_message_at_num INTEGER NOT NULL DEFAULT 0,
      message_count INTEGER NOT NULL DEFAULT 0,
      metadata_json TEXT NOT NULL DEFAULT '{}'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS events (
      seq INTEGER PRIMARY KEY AUTOINCREMENT,
      id TEXT NOT NULL UNIQUE,
      session_id TEXT NOT NULL,
      turn_id TEXT NOT NULL DEFAULT '',
      event_type TEXT NOT NULL,
      role TEXT NOT NULL,
      content TEXT NOT NULL DEFAULT '',
      thought TEXT NOT NULL DEFAULT '',
      tool_call_id TEXT NOT NULL DEFAULT '',
      tool_name TEXT NOT NULL DEFAULT '',
      tool_args_json TEXT NOT NULL DEFAULT '',
      tool_calls_json TEXT NOT NULL DEFAULT '',
      metadata_json TEXT NOT NULL DEFAULT '{}',
      revision INTEGER NOT NULL DEFAULT 1,
      timestamp TEXT NOT NULL,
      timestamp_num INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      deleted_at TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_events_session_seq ON events(session_id, seq)",
    "CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)",
    "CREATE INDEX IF NOT EXISTS idx_events_deleted ON events(deleted_at)",
    """
    CREATE TABLE IF NOT EXISTS token_usage (
      id TEXT PRIMARY KEY,
      session_id TEXT NOT NULL DEFAULT '',
      turn_id TEXT NOT NULL DEFAULT '',
      owner_user_id TEXT NOT NULL DEFAULT '',
      provider TEXT NOT NULL DEFAULT '',
      model TEXT NOT NULL DEFAULT '',
      prompt_tokens INTEGER NOT NULL DEFAULT 0,
      completion_tokens INTEGER NOT NULL DEFAULT 0,
      total_tokens INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL,
      created_at_num INTEGER NOT NULL DEFAULT 0
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_token_usage_session ON token_usage(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_token_usage_created ON token_usage(created_at_num)",
    """
    CREATE TABLE IF NOT EXISTS memories (
      id TEXT PRIMARY KEY,
      kind TEXT NOT NULL,
      content TEXT NOT NULL,
      source_event_ids_json TEXT NOT NULL DEFAULT '[]',
      confidence REAL NOT NULL DEFAULT 0.5,
      importance REAL NOT NULL DEFAULT 0.5,
      session_id TEXT NOT NULL DEFAULT '',
      metadata_json TEXT NOT NULL DEFAULT '{}',
      revision INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      deleted_at TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_memories_kind_session ON memories(kind, session_id)",
    """
    CREATE TABLE IF NOT EXISTS session_summaries (
      session_id TEXT PRIMARY KEY,
      summary TEXT NOT NULL,
      covered_until_seq INTEGER NOT NULL DEFAULT 0,
      revision INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS embedding_jobs (
      id TEXT PRIMARY KEY,
      target_type TEXT NOT NULL,
      target_id TEXT NOT NULL,
      action TEXT NOT NULL,
      embedding_model TEXT NOT NULL DEFAULT '',
      target_revision INTEGER NOT NULL DEFAULT 0,
      status TEXT NOT NULL DEFAULT 'pending',
      attempts INTEGER NOT NULL DEFAULT 0,
      error TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_embedding_jobs_status ON embedding_jobs(status, created_at)",
    """
    CREATE TABLE IF NOT EXISTS vector_index_records (
      target_type TEXT NOT NULL,
      target_id TEXT NOT NULL,
      index_name TEXT NOT NULL,
      embedding_model TEXT NOT NULL,
      target_revision INTEGER NOT NULL,
      vector_dim INTEGER,
      indexed_at TEXT NOT NULL,
      PRIMARY KEY(target_type, target_id, index_name, embedding_model)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS files (
      id TEXT PRIMARY KEY,
      session_id TEXT NOT NULL DEFAULT '',
      event_id TEXT NOT NULL DEFAULT '',
      original_name TEXT NOT NULL,
      path TEXT NOT NULL,
      mime_type TEXT NOT NULL DEFAULT '',
      size_bytes INTEGER NOT NULL DEFAULT 0,
      sha256 TEXT NOT NULL DEFAULT '',
      metadata_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS schedules (
      id TEXT PRIMARY KEY,
      session_id TEXT NOT NULL DEFAULT '',
      schedule_type TEXT NOT NULL,
      payload_json TEXT NOT NULL DEFAULT '{}',
      next_fire_at TEXT,
      status TEXT NOT NULL DEFAULT 'active',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_log (
      id TEXT PRIMARY KEY,
      actor TEXT NOT NULL DEFAULT '',
      action TEXT NOT NULL,
      target_type TEXT NOT NULL DEFAULT '',
      target_id TEXT NOT NULL DEFAULT '',
      before_json TEXT,
      after_json TEXT,
      created_at TEXT NOT NULL
    )
    """,
]
