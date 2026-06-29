import json
import sqlite3

from yumi.core.features.config.store import load_saved_model_config, save_model_config
from yumi.core.features.memory.memory import Memory
from yumi.core.features.proactive.state import ProactiveStateStore
from yumi.core.features.proactive.timer_tools import SchedulerService
from yumi.core.features.uploads import service as upload_service
from yumi.core.platform.storage.sqlite_store import SQLiteStore, db_path_for_config_path


def test_sqlite_schema_creates_canonical_tables(tmp_path):
    db_path = tmp_path / "yumi.db"
    SQLiteStore(db_path)

    with sqlite3.connect(db_path) as conn:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

    assert {
        "db_meta",
        "settings",
        "secrets",
        "model_profiles",
        "prompts",
        "tool_policies",
        "sessions",
        "events",
        "memories",
        "session_summaries",
        "embedding_jobs",
        "vector_index_records",
        "files",
        "schedules",
        "audit_log",
    }.issubset(names)


def test_config_json_migrates_to_sqlite_and_save_keeps_legacy_mirror(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"chat_model": "old", "openai_api_key": "sk-old"}), encoding="utf-8")
    monkeypatch.setattr("yumi.core.features.config.store.CONFIG_PATH", config_path)

    cfg = load_saved_model_config()
    assert cfg.chat_model == "old"
    assert cfg.openai_api_key == "sk-old"

    cfg.chat_model = "new"
    save_model_config(cfg)

    assert load_saved_model_config().chat_model == "new"
    assert json.loads(config_path.read_text(encoding="utf-8"))["chat_model"] == "new"

    store = SQLiteStore(db_path_for_config_path(config_path))
    data = store.load_model_config_dict()
    assert data["chat_model"] == "new"
    assert data["openai_api_key"] == "sk-old"


def test_memory_writes_sqlite_events_and_tool_jobs(tmp_path):
    m = Memory(session_id="s", storage_dir=tmp_path, max_recent=50)
    user_id = m.add_message("user", "hello")
    m.persist_openai_messages(
        [
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "demo", "arguments": {}}}]},
            {"role": "tool", "name": "demo", "content": "done"},
        ]
    )

    rows = m.list_messages(session_id="s", limit=10)
    assert rows[0]["id"] == user_id
    assert [row["role"] for row in rows] == ["user", "assistant", "tool"]

    ctx = m.get_context(query=None)
    assert any(item.get("role") == "assistant" and item.get("tool_calls") for item in ctx)
    assert any(item.get("role") == "tool" and item.get("name") == "demo" for item in ctx)

    with sqlite3.connect(tmp_path / "yumi.db") as conn:
        event_types = [row[0] for row in conn.execute("SELECT event_type FROM events ORDER BY seq")]
        pending_jobs = conn.execute("SELECT COUNT(*) FROM embedding_jobs WHERE status='pending'").fetchone()[0]

    assert event_types == ["user_message", "assistant_tool_calls", "tool_result"]
    assert pending_jobs >= 3


def test_lancedb_chat_history_can_rebuild_from_sqlite_events(tmp_path):
    m = Memory(session_id="s", storage_dir=tmp_path, max_recent=50)
    m.add_message("user", "canonical")
    m.db.drop_table("chat_history", ignore_missing=True)

    rebuilt = Memory(session_id="s", storage_dir=tmp_path, max_recent=50)

    rows = rebuilt.messages.list(session_id="s", limit=10)
    assert [row["content"] for row in rows] == ["canonical"]


def test_upload_metadata_is_recorded_in_sqlite(tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    monkeypatch.setattr(upload_service, "uploads_root", lambda: uploads)

    result = upload_service.save_uploaded_file("s", "note.txt", b"hello")

    with sqlite3.connect(tmp_path / "yumi.db") as conn:
        row = conn.execute("SELECT session_id, original_name, path, size_bytes, sha256 FROM files").fetchone()

    assert row[0] == "s"
    assert row[1] == "note.txt"
    assert row[2] == result["path"]
    assert row[3] == 5
    assert len(row[4]) == 64


def test_schedules_are_recorded_in_sqlite(tmp_path):
    schedules_path = tmp_path / "schedules.json"
    scheduler = SchedulerService(schedules_path=schedules_path)
    scheduler.active_timers["abc"] = {
        "id": "abc",
        "type": "scheduled",
        "description": "demo",
        "session_id": "s",
        "next_fire_at": "2030-01-01T00:00:00",
        "created_at": "2029-01-01T00:00:00",
    }

    scheduler._save_schedules()

    with sqlite3.connect(tmp_path / "yumi.db") as conn:
        count = conn.execute("SELECT COUNT(*) FROM schedules WHERE id='abc'").fetchone()[0]

    restored = SchedulerService(schedules_path=schedules_path)._load_schedules()
    assert count == 1
    assert restored[0]["id"] == "abc"


def test_proactive_state_is_recorded_in_sqlite(tmp_path):
    path = tmp_path / "proactive_state.json"
    store = ProactiveStateStore(path=path)

    store.record_user_message("s")

    with sqlite3.connect(tmp_path / "yumi.db") as conn:
        row = conn.execute(
            "SELECT value_json FROM settings WHERE namespace='proactive_state' AND key='s'"
        ).fetchone()

    assert row is not None
    restored = ProactiveStateStore(path=path).get("s")
    assert restored.last_user_message_at is not None
