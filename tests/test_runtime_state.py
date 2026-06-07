import asyncio

from yumi.core.platform.runtime import RuntimeState, build_runtime


def test_runtime_state_creates_isolated_registries():
    a = build_runtime()
    b = build_runtime()

    a.edge_registry.active_connections["edge-a"] = object()
    a.edge_registry.tools["edge-a"] = {"edge_edge-a__ping": {"schema": {}}}
    a.timer_registry.tasks["timer-a"] = object()
    a.tool_policy.disabled_tools.add("dangerous_tool")

    assert "edge-a" not in b.edge_registry.active_connections
    assert "edge-a" not in b.edge_registry.tools
    assert "timer-a" not in b.timer_registry.tasks
    assert "dangerous_tool" not in b.tool_policy.disabled_tools


def test_session_lock_registry_reuses_lock_per_session():
    runtime = RuntimeState()

    first = runtime.session_locks.get("default")
    second = runtime.session_locks.get("default")

    assert isinstance(first, asyncio.Lock)
    assert first is second


def test_tool_catalog_reads_runtime_edge_registry(monkeypatch):
    runtime = RuntimeState()
    runtime.edge_registry.tools["edge-a"] = {
        "edge_edge-a__ping": {
            "schema": {"type": "function", "function": {"name": "edge_edge-a__ping"}},
        }
    }

    class _Scope:
        def filter_edge_tool_schemas(self, identity, registry, disabled):
            return [
                entry["schema"] for tools in registry.values() for name, entry in tools.items() if name not in disabled
            ]

    monkeypatch.setattr("yumi.core.platform.plugins.get_edge_scope", lambda: _Scope())

    schemas = runtime.tool_catalog.all_tool_schemas()

    assert any(s["function"]["name"] == "edge_edge-a__ping" for s in schemas)
