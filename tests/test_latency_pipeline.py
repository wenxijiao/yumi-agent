"""Regression coverage for non-blocking preparation and incremental audio."""

from __future__ import annotations

import asyncio
import contextvars
import sqlite3
from contextlib import ExitStack

import pytest
from yumi.core.features.config import ModelConfig
from yumi.core.features.memory import index_queue
from yumi.core.features.memory.memory import Memory
from yumi.core.platform.runtime.async_work import run_blocking
from yumi.core.platform.tools import context_prefetch as prefetch


@pytest.fixture(autouse=True)
def _isolate_index_configuration(tmp_path, monkeypatch):
    # Queue regressions must not depend on a developer's configured model or
    # contact a live embedding service. Individual tests can supply a provider.
    monkeypatch.setattr("yumi.core.features.config.paths.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("yumi.core.features.memory.memory.load_model_config", lambda: ModelConfig(embedding_model=None))
    monkeypatch.setattr("yumi.core.features.memory.memory.get_embed_provider", lambda: None)


def test_deferred_index_preserves_canonical_history_and_resumes_after_reopen(tmp_path, monkeypatch):
    monkeypatch.setattr(index_queue, "start_worker", lambda _: None)
    memory = Memory(session_id="latency", storage_dir=tmp_path)
    token = index_queue.defer_message_index.set(True)
    try:
        message_id = memory.add_message("user", "A small test message.")
    finally:
        index_queue.defer_message_index.reset(token)
    assert memory.sqlite.get_message(message_id)["content"] == "A small test message."
    assert memory.messages.get(message_id) is None
    assert any("A small test message." in str(m.get("content")) for m in memory.get_context())
    reopened = Memory(session_id="latency", storage_dir=tmp_path)
    index_queue._drain(reopened)
    assert reopened.messages.get(message_id)["content"] == "A small test message."
    with reopened.sqlite.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM message_index_jobs").fetchone()[0] == 0


def test_deleted_message_is_not_resurrected_by_delayed_embedding(tmp_path, monkeypatch):
    monkeypatch.setattr(index_queue, "start_worker", lambda _: None)
    memory = Memory(session_id="latency", storage_dir=tmp_path)
    token = index_queue.defer_message_index.set(True)
    try:
        message_id = memory.add_message("user", "Delete while indexing.")
    finally:
        index_queue.defer_message_index.reset(token)

    def embed(_):
        memory.sqlite.delete_message(message_id)
        return [0.0] * memory.embedding.fallback_vector_size

    monkeypatch.setattr(memory.embedding, "get_vector", embed)
    monkeypatch.setattr(memory.embedding, "embed_model", None)
    index_queue._drain(memory)
    assert memory.sqlite.get_message(message_id) is None
    assert memory.messages.get(message_id) is None


def test_prefetch_reads_run_together_keep_order_and_skip_slow_optional_sources(monkeypatch):
    entries = {
        name: {"proactive_context": True, "schema": {"function": {"name": name, "parameters": {}}}}
        for name in ["first", "second", "slow", "forbidden"]
    }
    monkeypatch.setattr(prefetch, "TOOL_REGISTRY", entries)
    monkeypatch.setattr(prefetch, "EDGE_TOOLS_REGISTRY", {})
    monkeypatch.setattr(prefetch, "CONFIRMATION_TOOLS", {"forbidden"})
    monkeypatch.setattr(prefetch, "DISABLED_TOOLS", set())
    monkeypatch.setattr(prefetch, "CONTEXT_PREFETCH_BUDGET_SECONDS", 0.05)

    async def run():
        started = set()
        all_fast_started = asyncio.Event()
        cancelled = []

        async def execute(name, args):
            started.add(name)
            if {"first", "second"} <= started:
                all_fast_started.set()
            if name == "slow":
                try:
                    await asyncio.Future()
                finally:
                    cancelled.append(name)
            await all_fast_started.wait()
            return name

        monkeypatch.setattr(prefetch, "execute_registered_tool", execute)
        result = await prefetch.context_prefetch_items()
        assert [x.result for x in result] == ["first", "second"]
        assert cancelled == ["slow"]
        assert "forbidden" not in started

    asyncio.run(run())


def test_blocking_work_does_not_stall_loop_and_cancellation_waits_for_cleanup():
    import threading

    async def run():
        started, release = threading.Event(), threading.Event()
        finished = []

        def blocking():
            started.set()
            release.wait(timeout=2)
            finished.append(True)

        task = asyncio.create_task(run_blocking(blocking))
        while not started.is_set():
            await asyncio.sleep(0.001)
        task.cancel()
        await asyncio.sleep(0.005)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert finished == [True]

    asyncio.run(run())


def test_deferred_index_reuses_completed_request_vector(tmp_path, monkeypatch):
    from yumi.core.platform.runtime.embedding_cache import RequestEmbeddingCache, request_embedding_cache
    from yumi.core.platform.runtime.usage_context import usage_owner_id

    monkeypatch.setattr(index_queue, "start_worker", lambda _: None)
    memory = Memory(session_id="latency", storage_dir=tmp_path)
    provider = object()
    monkeypatch.setattr(memory.embedding, "embed_provider", provider)
    monkeypatch.setattr(memory.embedding, "embed_model", "test")
    vector = [0.5] * memory.embedding.fallback_vector_size
    cache = RequestEmbeddingCache()
    cache.get("alice", provider, "test", "Reuse me.", lambda: vector)
    tokens = [
        (request_embedding_cache, request_embedding_cache.set(cache)),
        (usage_owner_id, usage_owner_id.set("alice")),
        (index_queue.defer_message_index, index_queue.defer_message_index.set(True)),
    ]
    try:
        message_id = memory.add_message("user", "Reuse me.")
        cache.close()
        monkeypatch.setattr(memory.embedding, "get_vector", lambda _: pytest.fail("Embedded twice"))
        index_queue._drain(memory)
        assert memory.messages.get(message_id)["content"] == "Reuse me."
        with memory.sqlite.connect() as conn:
            assert conn.execute("SELECT COUNT(*) FROM message_index_jobs").fetchone()[0] == 0
    finally:
        for var, token in reversed(tokens):
            var.reset(token)


@pytest.mark.parametrize("outcome", ["success", "retry", "empty", "database_error"])
def test_index_drain_keeps_job_attribution_and_restores_caller_context(tmp_path, monkeypatch, outcome):
    from yumi.core.platform.runtime.embedding_cache import RequestEmbeddingCache, request_embedding_cache
    from yumi.core.platform.runtime.usage_context import usage_operation, usage_owner_id, usage_turn_id

    monkeypatch.setattr(index_queue, "start_worker", lambda _: None)
    memory = Memory(session_id="latency", storage_dir=tmp_path)

    def enqueue(owner):
        usage_owner_id.set(owner)
        usage_turn_id.set(f"turn-{owner}")
        index_queue.defer_message_index.set(True)
        return memory.add_message("user", owner)

    messages = {owner: contextvars.copy_context().run(enqueue, owner) for owner in ("alice", "bob")}
    observed = []

    def embed(content):
        observed.append(
            (
                content,
                usage_owner_id.get(),
                usage_turn_id.get(),
                usage_operation.get(),
                request_embedding_cache.get(),
                index_queue.defer_message_index.get(),
            )
        )
        if outcome == "retry" and content == "alice":
            raise RuntimeError("Temporary embedding failure")
        return [0.5] * memory.embedding.fallback_vector_size

    monkeypatch.setattr(memory.embedding, "get_vector", embed)
    if outcome == "empty":
        with memory.sqlite.connect() as conn:
            conn.execute("DELETE FROM message_index_jobs")
    elif outcome == "database_error":

        def unavailable():
            raise sqlite3.OperationalError("Database unavailable")

        monkeypatch.setattr(memory.sqlite, "connect", unavailable)

    caller_state = {
        usage_owner_id: "caller",
        usage_turn_id: "caller-turn",
        usage_operation: "embedding",
        request_embedding_cache: RequestEmbeddingCache(),
        index_queue.defer_message_index: True,
    }
    with ExitStack() as context:
        for var, value in caller_state.items():
            context.callback(var.reset, var.set(value))
        if outcome == "database_error":
            with pytest.raises(sqlite3.OperationalError, match="Database unavailable"):
                index_queue._drain(memory)
        else:
            index_queue._drain(memory)
        assert {var: var.get() for var in caller_state} == caller_state

    if outcome in {"empty", "database_error"}:
        assert observed == []
        return
    assert observed == [(owner, owner, f"turn-{owner}", "message_index", None, False) for owner in ("alice", "bob")]
    assert memory.messages.get(messages["bob"])["content"] == "bob"
    with memory.sqlite.connect() as conn:
        pending = conn.execute("SELECT event_id, attempts FROM message_index_jobs").fetchall()
    if outcome == "retry":
        assert [tuple(row) for row in pending] == [(messages["alice"], 1)]
        assert memory.messages.get(messages["alice"]) is None
    else:
        assert pending == []
        assert memory.messages.get(messages["alice"])["content"] == "alice"
