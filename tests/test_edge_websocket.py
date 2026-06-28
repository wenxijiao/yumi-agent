"""Edge WebSocket handshake and tool registration tests (no real LLM).

Starlette TestClient runs WebSocket handlers on a background thread so
the server-side state is populated asynchronously.  We use a short poll
loop to wait for the registration to complete.
"""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient
from yumi.core.api import app
from yumi.core.features.edge.api import handle_edge_peer
from yumi.core.features.edge.peers import EdgePeerDisconnected
from yumi.core.platform.plugins import get_edge_scope, register_plugin
from yumi.core.platform.runtime.accessors import ACTIVE_CONNECTIONS, EDGE_TOOLS_REGISTRY


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
        from yumi.core.platform.runtime.edge_naming import edge_tool_key_prefix

        prefixed = f"{edge_tool_key_prefix('test-device')}ping"
        entry = EDGE_TOOLS_REGISTRY.get("test-device", {}).get(prefixed)
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


def test_edge_duplicate_name_is_rejected():
    """A second edge claiming an already-active name is refused; the first stays.

    This is the safeguard that stops two different edges from fighting over one
    name (which used to make them ping-pong-kick each other).
    """
    client = TestClient(app)

    def _register(name: str) -> dict:
        return {
            "type": "register",
            "edge_name": name,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "ping",
                        "description": "Returns pong",
                        "parameters": {"type": "object", "properties": {}, "required": []},
                    },
                }
            ],
        }

    with client.websocket_connect("/ws/edge") as ws1:
        ws1.send_json(_register("dup-device"))
        assert _wait_for_edge("dup-device"), "First edge did not register."
        first_peer = ACTIVE_CONNECTIONS.get("dup-device")

        # A second edge with the same name must be rejected, not swap in.
        with client.websocket_connect("/ws/edge") as ws2:
            ws2.send_json(_register("dup-device"))
            msg = ws2.receive_json()
            assert msg["type"] == "register_rejected"
            assert "dup-device" in msg["reason"]

        # The original edge is untouched and still the active connection.
        assert ACTIVE_CONNECTIONS.get("dup-device") is first_peer


def test_edge_registration_uses_scope_for_connection_key_and_tool_prefix():
    class ScopedEdgeScope:
        def __init__(self):
            self.connection_args = []
            self.prefix_args = []
            self.registered = []
            self.disconnected = []

        def connection_key(self, owner_user_id: str | None, edge_name: str) -> str:
            self.connection_args.append((owner_user_id, edge_name))
            return f"u:{owner_user_id}::{edge_name}"

        def tool_register_prefix(self, owner_user_id: str | None, edge_name: str) -> str:
            self.prefix_args.append((owner_user_id, edge_name))
            return f"edge_{owner_user_id}_{edge_name}__"

        def filter_edge_tool_schemas(self, identity, registry: dict[str, dict], disabled: set[str]) -> list:  # noqa: ARG002
            return []

        def on_edge_register(self, connection_key: str, auth_msg: dict) -> None:  # noqa: ARG002
            self.registered.append((connection_key, list(EDGE_TOOLS_REGISTRY.get(connection_key, {}))))

        def on_edge_disconnect(self, connection_key: str) -> None:
            self.disconnected.append(connection_key)

    class FakePeer:
        def __init__(self):
            self.sent = []
            self.closed = False
            self._registered = False

        async def receive_json(self):
            if self._registered:
                raise EdgePeerDisconnected()
            self._registered = True
            return {
                "type": "register",
                "owner_user_id": "u42",
                "edge_name": "garage",
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "ping",
                            "description": "Returns pong",
                            "parameters": {"type": "object", "properties": {}, "required": []},
                        },
                    }
                ],
            }

        async def send_json(self, payload):
            self.sent.append(payload)

        async def close(self, code=1000, reason=""):  # noqa: ARG002
            self.closed = True

    previous_scope = get_edge_scope()
    scope = ScopedEdgeScope()
    register_plugin(edge_scope=scope)
    try:
        asyncio.run(handle_edge_peer(FakePeer()))
    finally:
        register_plugin(edge_scope=previous_scope)

    assert scope.connection_args == [("u42", "garage")]
    assert scope.prefix_args == [("u42", "garage")]
    assert scope.registered == [("u:u42::garage", ["edge_u42_garage__ping"])]
    assert scope.disconnected == ["u:u42::garage"]
