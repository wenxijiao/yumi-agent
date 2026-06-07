"""Monitor HTTP routes (local core, no Relay)."""

from fastapi.testclient import TestClient
from kumi.core.api import app


def test_monitor_topology_ok():
    c = TestClient(app)
    r = c.get("/monitor/topology")
    assert r.status_code == 200
    data = r.json()
    assert data.get("server", {}).get("id") == "kumi-core"
    assert "local_tool_count" in data
    assert isinstance(data.get("edges"), list)


def test_monitor_traces_ok():
    c = TestClient(app)
    r = c.get("/monitor/traces?limit=10")
    assert r.status_code == 200
    assert "traces" in r.json()


def test_monitor_traces_export_content_type():
    c = TestClient(app)
    r = c.get("/monitor/traces/export")
    assert r.status_code == 200
    assert "ndjson" in r.headers.get("content-type", "")
