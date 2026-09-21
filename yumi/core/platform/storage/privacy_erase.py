"""Erase a dedicated user's assistant data without touching shared identities."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from yumi.core.features.assistant.personalization import BEHAVIOR_KINDS, STABLE_CONTEXT
from yumi.core.platform.storage.assistant_store import AssistantStore, is_group_session


def erase_assistant_data(memory, owner, qualify, *, account=False, memories=False):
    """Caller must hold the owner's exclusive privacy lease.

    Canonical data is purged first. Retrying after any filesystem/index error
    is safe; a durable maintenance tombstone keeps all readers out meanwhile.
    """
    sqlite = memory.sqlite
    from yumi.core.features.config.paths import CONFIG_DIR

    expected = CONFIG_DIR / "users" / owner / "yumi.db"
    if not owner or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in owner):
        raise ValueError("Invalid account identifier")
    if (
        sqlite.db_path.resolve() != expected.resolve()
        or expected.parent.resolve() != (CONFIG_DIR / "users").resolve() / owner
    ):
        raise ValueError("Erasure requires a dedicated per-user database")
    prefix = f"u_{owner}__"
    with sqlite.connect() as conn:
        conn.execute("PRAGMA secure_delete=ON")
        conn.execute("BEGIN IMMEDIATE")
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        sessions = {
            row[0]
            for table in ("sessions", "events", "turn_traces", "session_summaries", "files", "schedules")
            for row in conn.execute(f"SELECT DISTINCT session_id FROM {table}")
            if row[0] is not None and (account or not is_group_session(row[0]))
        }
        if "voice_messages" in tables:
            sessions.update(
                row[0]
                for row in conn.execute("SELECT DISTINCT session_id FROM voice_messages WHERE owner=?", (owner,))
                if row[0] is not None and (account or not is_group_session(row[0]))
            )
        if "tool_runs" in tables:
            sessions.update(
                row[0]
                for row in conn.execute(
                    "SELECT json_extract(record_json,'$.session_id') FROM tool_runs WHERE owner=?", (owner,)
                )
                if row[0] is not None and (account or not is_group_session(row[0]))
            )
        current = AssistantStore(sqlite, owner)._read(conn, "state", None)
        if current:
            sessions.add(current["session_id"])
        conn.execute("CREATE TABLE IF NOT EXISTS erased_sessions(session_id TEXT PRIMARY KEY)")
        conn.executemany("INSERT OR IGNORE INTO erased_sessions VALUES(?)", [(s,) for s in sessions])
        for table in ("events", "turn_traces", "session_summaries", "files", "schedules", "sessions"):
            conn.executemany(f"DELETE FROM {table} WHERE session_id=?", [(s,) for s in sessions])
        if "voice_messages" in tables:
            conn.executemany(
                "DELETE FROM voice_messages WHERE owner=? AND session_id=?", [(owner, s) for s in sessions]
            )
            if account:
                conn.execute("DELETE FROM voice_messages WHERE owner=?", (owner,))
        if "tool_runs" in tables:
            conn.executemany(
                "DELETE FROM tool_runs WHERE owner=? AND json_extract(record_json,'$.session_id')=?",
                [(owner, s) for s in sessions],
            )
            if account:
                conn.execute("DELETE FROM tool_runs WHERE owner=?", (owner,))
        # Behavior rules are retained on history deletion. About-you memories
        # are an explicit opt-in; derived summaries/observations are always erased.
        for row in conn.execute("SELECT id,kind,deleted_at FROM memories").fetchall():
            remove = account or row["deleted_at"] or row["kind"] in {"summary", "tool_observation", "task_state"}
            remove = remove or (memories and row["kind"] not in BEHAVIOR_KINDS)
            if remove:
                conn.execute("DELETE FROM memories WHERE id=?", (row["id"],))
            else:
                conn.execute(
                    "UPDATE memories SET source_event_ids_json='[]',session_id=?,metadata_json='{}' WHERE id=?",
                    (STABLE_CONTEXT, row["id"]),
                )
        conn.executemany("DELETE FROM prompts WHERE scope='session' AND session_id=?", [(s,) for s in sessions])
        # Local mutation audit snapshots may contain message bodies; operational
        # access audit metadata is kept separately in the tenancy database.
        conn.execute("DELETE FROM audit_log")
        if account:
            for table in ("settings", "secrets", "model_profiles", "prompts", "tool_policies", "token_usage"):
                conn.execute(f"DELETE FROM {table}")
        else:
            conn.execute(
                "DELETE FROM settings WHERE namespace=? AND key IN ('state','tool_references')", (f"assistant:{owner}",)
            )
        # Rotate the active segment without ever reusing a previous revision.
        import uuid
        from datetime import datetime, timezone

        AssistantStore(sqlite, owner)._write(
            conn,
            "state",
            {
                "session_id": qualify(f"personal_{uuid.uuid4().hex}"),
                "revision": (current or {}).get("revision", 0) + 1,
                "started_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        retained = {row[0] for row in conn.execute("SELECT id FROM memories")}
    # Keep original vectors for retained memories/group history. Replacing a
    # table drops old fragments as well as searchable rows, without re-embedding.
    for name in memory.backend.list_table_names():
        table = memory.db.open_table(name)
        rows = table.to_arrow().to_pylist()
        if name == memory.long_term_table_name:
            kept = [r for r in rows if r.get("id") in retained]
            for row in kept:
                if "source_message_ids" in row:
                    row["source_message_ids"] = "[]" if isinstance(row["source_message_ids"], str) else []
                if "source_message_ids_json" in row:
                    row["source_message_ids_json"] = "[]"
                if "session_id" in row:
                    row["session_id"] = STABLE_CONTEXT
        else:
            kept = [r for r in rows if not account and is_group_session(str(r.get("session_id", "")))]
        schema = table.schema
        memory.db.create_table(name, data=kept, schema=schema, mode="overwrite")
        # Remove superseded fragments, including historical versions containing
        # erased messages. No old reader may hold a lease during this operation.
        from datetime import timedelta

        memory.db.open_table(name).optimize(cleanup_older_than=timedelta(0), delete_unverified=True)
    from yumi.core.features.uploads.service import uploads_root

    upload_root = uploads_root().resolve()
    user_uploads = upload_root / owner
    if not user_uploads.resolve().is_relative_to(upload_root) or user_uploads.is_symlink():
        raise ValueError("Invalid private upload path")
    if account:
        shutil.rmtree(user_uploads, ignore_errors=False) if user_uploads.exists() else None
    elif user_uploads.exists():
        # Include unsent private uploads, but preserve group attachments.
        for directory in user_uploads.iterdir():
            if not is_group_session(directory.name):
                if directory.is_dir() and not directory.is_symlink():
                    shutil.rmtree(directory)
                else:
                    directory.unlink()
    voice_root = sqlite.db_path.parent / "voice" / hashlib.sha256(owner.encode()).hexdigest()[:32]
    if voice_root.exists():
        with sqlite.connect() as conn:
            keep_files = set()
            if "voice_messages" in tables:
                for row in conn.execute("SELECT parts_json FROM voice_messages WHERE owner=?", (owner,)):
                    keep_files.update(part["filename"] for part in json.loads(row[0]))
        for file in voice_root.iterdir():
            if file.is_file() and file.name not in keep_files:
                file.unlink()
    from yumi.core.platform.providers.diagnostics import debug_dir

    for file in Path(debug_dir()).glob("*.json"):
        # Diagnostic snapshots are shared by the deployment: only remove files
        # whose embedded owner-qualified session belongs to the erased scope.
        try:
            row = json.loads(file.read_text())
        except (ValueError, OSError):
            continue
        sid = str(row.get("session_id") or "")
        if sid.startswith(prefix) and (account or not is_group_session(sid)):
            file.unlink()
    from yumi.core.platform.observability.turn_inspector import clear_owner_turns

    clear_owner_turns(prefix, include_groups=account)
    with sqlite.connect() as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.execute("VACUUM")
    return {"status": "deleted", "deleted_sessions": len(sessions)}
