"""Protect task continuity, function visibility and auxiliary usage attribution."""

import asyncio
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from yumi.core.features.config import ModelConfig
from yumi.core.platform.providers.budget import fit_prompt, fit_tool_schemas, token_estimate
from yumi.core.platform.runtime.assistant_context import conversation_session
from yumi.core.platform.storage.sqlite_store import SQLiteStore
from yumi.core.platform.tools import routing


def test_concurrent_workers_can_upgrade_existing_usage_database(tmp_path):
    path = tmp_path / "yumi.db"
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE token_usage(id TEXT PRIMARY KEY, session_id TEXT, turn_id TEXT, owner_user_id TEXT, provider TEXT, model TEXT, prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER, created_at TEXT, created_at_num INTEGER)"
        )
    script = "from yumi.core.platform.storage.sqlite_store import SQLiteStore; import sys; SQLiteStore(sys.argv[1])"
    workers = [
        subprocess.Popen([sys.executable, "-c", script, str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        for _ in range(4)
    ]
    for worker in workers:
        _, error = worker.communicate(timeout=30)
        assert worker.returncode == 0, error.decode()
    with sqlite3.connect(path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(token_usage)")}
        assert {"usage_kind", "estimated"} <= columns


def schema(name, description=""):
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": {"type": "object", "properties": {}}},
    }


def test_budget_drops_whole_completed_turn_and_keeps_task_tool_pairs():
    messages = [
        {"role": "system", "content": "RULES"},
        {"role": "user", "content": "OLD" * 5000},
        {"role": "assistant", "tool_calls": [{"id": "old", "function": {"name": "read", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "old", "content": "old result"},
        {"role": "system", "content": "RECALLED FACT"},
        {"role": "user", "content": "CURRENT TASK"},
        {"role": "assistant", "tool_calls": [{"id": "new", "function": {"name": "read", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "new", "content": "RESULT" * 5000},
    ]
    fitted = fit_prompt(messages, [schema("read")], budget=1500, current_user_index=5)
    assert token_estimate(fitted) + token_estimate([schema("read")]) <= 1500
    assert [m["content"] for m in fitted if m["role"] in ("system", "user")] == [
        "RULES",
        "RECALLED FACT",
        "CURRENT TASK",
    ]
    assert [m["tool_call_id"] for m in fitted if m["role"] == "tool"] == ["new"]
    assert "shortened" in fitted[-1]["content"]
    assert len(messages[-1]["content"]) == 30000
    with pytest.raises(ValueError, match="context budget"):
        fit_prompt(
            [{"role": "system", "content": "RULES" * 2000}, {"role": "user", "content": "TASK"}], None, budget=100
        )


def test_tool_budget_prefers_new_discovery_and_retains_discovery_function():
    tools = [schema("old", "x" * 1800), schema("discover_app_tools"), schema("new", "y" * 1800)]
    result = fit_tool_schemas(tools, budget=1000, priority_names=["new"])
    assert [s["function"]["name"] for s in result] == ["discover_app_tools", "new"]


def test_on_demand_small_catalog_never_runs_embedding_search(monkeypatch):
    monkeypatch.setattr(routing, "load_model_config", lambda: ModelConfig(edge_tools_routing_mode="on_demand"))
    monkeypatch.setattr(
        routing, "TOOL_REGISTRY", {n: {"schema": schema(n)} for n in ("discover_app_tools", "read_file", "unused")}
    )
    monkeypatch.setattr(
        "yumi.core.platform.tools.retrieval.rank_tools", lambda *a, **k: pytest.fail("small catalog must not search")
    )
    decision = routing.select_tool_schemas(
        query="hello",
        session_id="s",
        disabled_tools=set(),
        edge_registry={"lab": {"edge_lab__unused": {"schema": schema("edge_lab__unused")}}},
    )
    assert [t["function"]["name"] for t in decision.tools] == [
        "discover_app_tools",
        "read_file",
        "unused",
        "edge_lab__unused",
    ]


def test_discovery_obeys_personal_policy_and_does_not_expand_siblings(monkeypatch):
    import json

    from yumi.core.platform.plugins import Identity
    from yumi.core.platform.runtime import RuntimeState
    from yumi.tools import edge_discovery_tools as discovery

    names = ["edge_lab__weather", "edge_lab__disabled_weather", "edge_lab__denied_weather", "edge_lab__delete"]
    runtime = RuntimeState()
    runtime.edge_registry.tools["lab"] = {
        n: {"schema": schema(n, "weather" if "weather" in n else "delete files")} for n in names
    }
    identity = Identity(user_id="alice")
    cfg = ModelConfig(embedding_model=None)
    monkeypatch.setattr(routing, "load_model_config", lambda: cfg)
    monkeypatch.setattr(routing, "TOOL_REGISTRY", {})
    monkeypatch.setattr(discovery, "get_default_runtime", lambda: runtime)
    monkeypatch.setattr(discovery, "get_current_identity", lambda: identity)
    monkeypatch.setattr(
        "yumi.core.platform.plugins.get_session_scope",
        lambda: SimpleNamespace(owner_user_from_session_id=lambda sid: "alice"),
    )
    monkeypatch.setattr(
        "yumi.core.platform.runtime.assistant_context.personal_store",
        lambda owner: SimpleNamespace(
            get=lambda *args: {names[1]: {"disabled": True}, names[2]: {"ai_access": "none"}}
        ),
    )
    token = conversation_session.set("u_alice__personal_1")
    try:
        result = json.loads(discovery.discover_app_tools("weather", session_id="u_bob__personal_2"))
    finally:
        conversation_session.reset(token)
    assert result["activated_tool_names"] == [names[0]]
    assert (
        names[1] not in json.dumps(result) and names[2] not in json.dumps(result) and names[3] not in json.dumps(result)
    )


def test_vector_cache_survives_memory_reset_and_never_stores_query_text(tmp_path, monkeypatch):
    monkeypatch.setattr("yumi.core.features.config.paths.CONFIG_DIR", tmp_path)
    calls = []

    class Provider:
        def embed(self, model, text):
            calls.append(text)
            return [1.0, 2.0]

    provider = Provider()
    monkeypatch.setattr(routing, "get_embed_provider", lambda: provider)
    routing._EMBED_CACHE.clear()
    routing._EMBED_CACHE_ORDER.clear()
    routing._cached_embedding("test", "tool description", persistent=True)
    routing._cached_embedding("test", "PRIVATE QUERY")
    routing._EMBED_CACHE.clear()
    routing._cached_embedding("test", "tool description", persistent=True)
    assert calls == ["tool description", "PRIVATE QUERY"]
    with sqlite3.connect(tmp_path / "tool-vectors.sqlite3") as conn:
        assert conn.execute("SELECT COUNT(*) FROM vectors").fetchone()[0] == 1
    assert b"PRIVATE QUERY" not in (tmp_path / "tool-vectors.sqlite3").read_bytes()
    routing._EMBED_CACHE.clear()
    routing._EMBED_CACHE_ORDER.clear()


def test_auxiliary_usage_migration_totals_and_owner_isolation(tmp_path, monkeypatch):
    from yumi.core.features.memory.compaction import _summarize
    from yumi.core.features.memory.embedding_state import _MeteringEmbedWrapper
    from yumi.core.platform.plugins import Identity
    from yumi.core.platform.runtime.usage_context import (
        embedding_tokens,
        usage_operation,
        usage_owner_id,
        usage_turn_id,
    )
    from yumi.core.platform.storage.assistant_store import AssistantStore

    path = tmp_path / "yumi.db"
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE token_usage(id TEXT PRIMARY KEY, session_id TEXT, turn_id TEXT, owner_user_id TEXT, provider TEXT, model TEXT, prompt_tokens INTEGER, completion_tokens INTEGER, total_tokens INTEGER, created_at TEXT, created_at_num INTEGER)"
        )
    ledger = SQLiteStore(path)
    ledger.record_token_usage(session_id="s", owner_user_id="alice", prompt_tokens=10)
    ledger.record_token_usage(session_id="s", owner_user_id="bob", prompt_tokens=999)
    monkeypatch.setattr("yumi.core.features.config.paths.CONFIG_DIR", tmp_path)
    monkeypatch.setattr("yumi.core.platform.plugins.get_current_identity", lambda: Identity(user_id="alice"))

    class Provider:
        def embed(self, model, text):
            embedding_tokens.set(7)
            return [1.0]

        async def chat_stream(self, **kwargs):
            yield {"type": "text", "content": "summary"}
            yield {"type": "usage", "prompt_tokens": 20, "completion_tokens": 3}
            yield {"type": "finish", "reason": "stop"}

    provider = Provider()
    owner_token = usage_owner_id.set("alice")
    turn_token = usage_turn_id.set("turn-one")
    try:
        _MeteringEmbedWrapper(provider).embed("embed", "你好")
        asyncio.run(_summarize(SimpleNamespace(provider=provider, model_name="summary-model"), "summarize"))
        operation_token = usage_operation.set("tool_index")
        try:
            _MeteringEmbedWrapper(provider).embed("embed", "tool metadata")
        finally:
            usage_operation.reset(operation_token)
    finally:
        usage_owner_id.reset(owner_token)
        usage_turn_id.reset(turn_token)
    result = AssistantStore(ledger, "alice").monthly_usage(datetime.now(timezone.utc).strftime("%Y-%m"), "UTC")
    assert result["total_tokens"] == 40
    assert result["requests"] == 1
    assert result["by_kind"] == {"chat": 10, "embedding": 7, "summary": 23}
    assert all(row["estimated"] == 0 for row in result["recent"])
    assert all(row["turn_id"] == "turn-one" for row in result["recent"] if row["usage_kind"] != "chat")
