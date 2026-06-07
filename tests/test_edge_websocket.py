"""Edge WebSocket handshake and tool registration tests (no real LLM).

Starlette TestClient runs WebSocket handlers on a background thread so
the server-side state is populated asynchronously.  We use a short poll
loop to wait for the registration to complete.
"""

import time

import pytest
from fastapi.testclient import TestClient
from kumi.core.api import app
from kumi.core.platform.runtime.accessors import ACTIVE_CONNECTIONS, EDGE_TOOLS_REGISTRY


@pytest.fixture(autouse=True)
def _cleanup_edge_state():
    yield
    ACTIVE_CONNECTIONS.clear()
    EDGE_TOOLS_REGISTRY.clear()


def _wait_for_edge(edge_name: str, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if edge_name in ACTIVE_CONNECTIONS:
            return True
        time.sleep(0.05)
    return False


def test_edge_websocket_register_and_disconnect():
    client = TestClient(app)

    with client.websocket_connect("/ws/edge") as ws:
        ws.send_json(
            {
                "type": "register",
                "edge_name": "test-device",
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "ping",
                            "description": "Returns pong",
                            "parameters": {"type": "object", "properties": {}, "required": []},
                        },
                        "always_include": True,
                        "allow_proactive": True,
                        "proactive_context": True,
                        "proactive_context_args": {"location": "Auckland"},
                        "proactive_context_description": "Current weather",
                    }
                ],
            }
        )
        assert _wait_for_edge("test-device"), "Edge device did not register in time."
        entry = EDGE_TOOLS_REGISTRY.get("test-device", {}).get("edge_test-device__ping")
        assert entry is not None
        assert entry["always_include"] is True
        assert entry["allow_proactive"] is True
        assert entry["proactive_context"] is True
        assert entry["proactive_context_args"] == {"location": "Auckland"}
        assert entry["proactive_context_description"] == "Current weather"
        assert "always_include" not in entry["schema"]
        assert "allow_proactive" not in entry["schema"]

    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if "test-device" not in ACTIVE_CONNECTIONS:
            break
        time.sleep(0.05)
    assert "test-device" not in ACTIVE_CONNECTIONS
