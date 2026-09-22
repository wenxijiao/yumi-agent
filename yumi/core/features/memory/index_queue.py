"""Durable, bounded message-index work. SQLite remains the source of truth.

Only chat turns opt in. The outbox contains IDs, never another copy of private
text. Workers re-read canonical messages under the owner's privacy lease and
ignore deleted/edited sources. Failed jobs survive process restarts.
"""

from __future__ import annotations

import contextvars
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from yumi.logging_config import get_logger

logger = get_logger(__name__)
defer_message_index = contextvars.ContextVar("defer_message_index", default=False)
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="yumi-index")
_lock = threading.Lock()
_running: set[str] = set()
_vectors: OrderedDict = OrderedDict()


def enqueue(memory, record):
    from yumi.core.platform.runtime.usage_context import usage_owner_id, usage_turn_id

    generation = uuid.uuid4().hex
    with memory.sqlite.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("""CREATE TABLE IF NOT EXISTS message_index_jobs (
            event_id TEXT PRIMARY KEY, owner TEXT NOT NULL, turn_id TEXT NOT NULL, generation TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0, available_at REAL NOT NULL DEFAULT 0
        )""")
        memory.sqlite.upsert_event_from_message(record, connection=conn)
        conn.execute(
            "INSERT INTO message_index_jobs(event_id,owner,turn_id,generation) VALUES(?,?,?,?) "
            "ON CONFLICT(event_id) DO UPDATE SET available_at=0,attempts=0,generation=excluded.generation,turn_id=excluded.turn_id",
            (record["id"], usage_owner_id.get() or "_local", usage_turn_id.get() or "", generation),
        )

    from yumi.core.platform.runtime.embedding_cache import request_embedding_cache

    cache = request_embedding_cache.get()
    provider, model = memory.embedding.embed_provider, memory.embedding.embed_model
    vector = cache.peek(usage_owner_id.get(), provider, model, record["content"]) if cache and model else None
    if vector is not None:
        with _lock:
            _vectors[(str(memory.sqlite.db_path), record["id"], generation)] = (provider, model, vector)
            while len(_vectors) > 128:
                _vectors.popitem(last=False)


def start_worker(memory):
    """Resume pending work on the next turn/open, with one worker per store."""
    if getattr(memory, "sqlite", None) is None:
        return
    key = str(memory.sqlite.db_path)
    with _lock:
        if key in _running:
            return
        with memory.sqlite.connect() as conn:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='message_index_jobs'").fetchone():
                return
            if not conn.execute(
                "SELECT 1 FROM message_index_jobs WHERE available_at<=? LIMIT 1", (time.time(),)
            ).fetchone():
                return
        _running.add(key)
    context = contextvars.copy_context()

    def run():
        try:
            context.run(_drain, memory)
        except Exception:
            logger.warning("Deferred message indexing paused; it will resume on the next turn", exc_info=True)
        finally:
            with _lock:
                _running.discard(key)

    _pool.submit(run)


def _drain(memory):
    # Keep job attribution and cache settings local even when maintenance or
    # tests drain synchronously, without start_worker's thread/context wrapper.
    contextvars.copy_context().run(_drain_in_context, memory)


def _drain_in_context(memory):
    from yumi.core.platform.runtime.embedding_cache import request_embedding_cache
    from yumi.core.platform.runtime.usage_context import usage_operation, usage_owner_id, usage_turn_id
    from yumi.core.platform.storage.privacy_guard import lease

    # A completed request cache must not be kept alive by background work.
    request_embedding_cache.set(None)
    defer_message_index.set(False)
    for _ in range(100):
        with memory.sqlite.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            job = conn.execute(
                "SELECT * FROM message_index_jobs WHERE available_at<=? ORDER BY rowid LIMIT 1", (time.time(),)
            ).fetchone()
            if job is None:
                return
            job = dict(job)
            # Claims also prevent channel workers in another process racing us.
            conn.execute(
                "UPDATE message_index_jobs SET available_at=? WHERE event_id=?", (time.time() + 300, job["event_id"])
            )
        usage_owner_id.set(job["owner"])
        usage_turn_id.set(job["turn_id"])
        usage_operation.set("message_index")
        try:
            with lease(job["owner"]):
                record = memory.sqlite.get_message(job["event_id"])
                if record is not None:
                    with _lock:
                        cached = _vectors.pop((str(memory.sqlite.db_path), record["id"], job["generation"]), None)
                    if (
                        cached
                        and cached[0] is memory.embedding.embed_provider
                        and cached[1] == memory.embedding.embed_model
                    ):
                        vector = cached[2]
                    else:
                        vector = memory.embedding.get_vector(record["content"])
                    if memory.embedding.embed_model and not any(vector):
                        raise RuntimeError("Embedding temporarily unavailable")
                    current = memory.sqlite.get_message(job["event_id"])
                    if current and current["content"] == record["content"]:
                        memory.messages.delete(record["id"])
                        memory.messages.create(
                            session_id=record["session_id"],
                            role=record["role"],
                            content=record["content"],
                            timestamp=record["timestamp"],
                            timestamp_num=record["timestamp_num"],
                            message_id=record["id"],
                            thought=record.get("thought"),
                            vector=vector,
                        )
                        # Individual message deletion does not take an exclusive
                        # account lease. Remove a result if its source changed.
                        current = memory.sqlite.get_message(job["event_id"])
                        if not current or current["content"] != record["content"]:
                            memory.messages.delete(record["id"])
                with memory.sqlite.connect() as conn:
                    conn.execute(
                        "DELETE FROM message_index_jobs WHERE event_id=? AND generation=?",
                        (job["event_id"], job["generation"]),
                    )
        except Exception:
            with memory.sqlite.connect() as conn:
                conn.execute(
                    "UPDATE message_index_jobs SET attempts=attempts+1,available_at=? WHERE event_id=? AND generation=?",
                    (time.time() + min(300, 2 ** min(job["attempts"] + 1, 8)), job["event_id"], job["generation"]),
                )
            logger.debug("Deferred index job retained for retry")
