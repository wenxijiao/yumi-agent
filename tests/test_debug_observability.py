"""Debug observability endpoint: edges snapshot + auto-diagnosis."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from yumi.core.api import app
from yumi.core.platform.runtime.accessors import ACTIVE_CONNECTIONS, EDGE_TOOLS_REGISTRY
from yumi.core.platform.runtime.edge_naming import edge_tool_key_prefix
from yumi.core.platform.tools.routing import (
    ToolRoutingDecision,
    clear_tool_routing_traces,
    record_tool_routing_trace,
)


@pytest.fixture(autouse=True)
def _clean():
    ACTIVE_CONNECTIONS.clear()
    EDGE_TOOLS_REGISTRY.clear()
    clear_tool_routing_traces()
    yield
    ACTIVE_CONNECTIONS.clear()
    EDGE_TOOLS_REGISTRY.clear()
    clear_tool_routing_traces()


def _mount_edge(edge_name: str = "my macbook", tool: str = "say_something") -> None:
    prefixed = f"{edge_tool_key_prefix(edge_name)}{tool}"
    EDGE_TOOLS_REGISTRY[edge_name] = {
        prefixed: {
            "schema": {"type": "function", "function": {"name": prefixed, "description": "Say something"}},
            "always_include": False,
            "require_confirmation": False,
        }
    }
    ACTIVE_CONNECTIONS[edge_name] = object()


def _record_trace(*, total: int, selected: int, session_id: str = "s1") -> None:
    picked = [SimpleNamespace(name=f"edge_sel_{i}") for i in range(selected)]
    decision = ToolRoutingDecision(
        tools=[],
        core_tools=[],
        selected_edge_tools=picked,
        total_edge_tools=total,
        dynamic_routing_enabled=True,
        elapsed_ms=1,
    )
    record_tool_routing_trace(session_id=session_id, query="say hi to my macbook", decision=decision)


def test_observability_reports_connected_edges_and_tools():
    _mount_edge()
    client = TestClient(app)

    data = client.get("/debug/observability").json()

    assert len(data["edges"]) == 1
    edge = data["edges"][0]
    assert edge["edge_name"] == "my macbook"
    assert edge["online"] is True
    assert edge["tool_count"] == 1
    assert edge["tools"][0]["name"] == "say_something"  # de-prefixed


def test_observability_flags_account_owner_mismatch():
    # Edge IS connected with a tool, but the chat turn saw 0 visible edge tools
    # (the hosted account/owner-scope mismatch). Diagnosis must call it out.
    _mount_edge()
    _record_trace(total=0, selected=0)
    client = TestClient(app)

    data = client.get("/debug/observability").json()

    assert any(d["level"] == "warning" and "mismatch" in d["message"] for d in data["diagnosis"])


def test_observability_flags_zero_selected_despite_visible():
    # Edge tools are visible to the identity, but routing selected none (e.g. limit=0).
    _mount_edge()
    _record_trace(total=1, selected=0)
    client = TestClient(app)

    data = client.get("/debug/observability").json()

    assert any(d["level"] == "warning" and "selected" in d["message"] for d in data["diagnosis"])


def test_observability_ok_when_edge_tools_reach_model():
    _mount_edge()
    _record_trace(total=1, selected=1)
    client = TestClient(app)

    data = client.get("/debug/observability").json()

    assert any(d["level"] == "ok" for d in data["diagnosis"])


def test_observability_reports_no_edges():
    client = TestClient(app)

    data = client.get("/debug/observability").json()

    assert data["edges"] == []
    assert any("No edge devices" in d["message"] for d in data["diagnosis"])
