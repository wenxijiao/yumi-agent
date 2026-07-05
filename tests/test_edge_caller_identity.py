"""Caller identity on edge tool calls.

The server stamps ``caller_user_id`` (the turn's authenticated principal)
onto every edge ``tool_call`` frame — OUTSIDE the model-generated
``arguments`` — so one shared edge can scope its work to the calling user.
The SDK hides the reserved param from LLM schemas, injects the frame value
into tools that declare it, fails closed when it is absent, and discards
any value smuggled into ``arguments``.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from yumi.core.platform.dispatch.context import ToolInvocation, TurnContext
from yumi.core.platform.dispatch.edge import EdgeToolExecutor
from yumi.core.platform.plugins.identity import (
    Identity,
    effective_caller_user_id,
    reset_current_identity,
    set_current_identity,
)
from yumi.core.platform.runtime import get_default_runtime
from yumi.sdk.python.agent_client import CALLER_PARAM, YumiAgent, _build_tool_schema

# ── helpers ────────────────────────────────────────────────────────────────


class _FramePeer:
    """Fake edge peer: captures the frame and resolves the pending future."""

    def __init__(self, runtime):
        self.runtime = runtime
        self.frames: list[dict] = []

    async def send_json(self, frame: dict) -> None:
        self.frames.append(frame)
        if frame.get("type") == "tool_call":
            pending = self.runtime.edge_registry.pending_tool_calls
            entry = pending.get(frame["call_id"])
            if entry is not None:
                entry["future"].set_result("ok")


def _edge_inv(caller: str | None) -> ToolInvocation:
    return ToolInvocation(
        kind="edge",
        func_name="edge_dev_do",
        tool_message_name="do",
        args={"x": 1},
        target_edge="dev",
        original_tool_name="do",
        caller_user_id=caller,
    )


class _FakeWs:
    def __init__(self):
        self.sent: list[dict] = []

    async def send(self, payload: str) -> None:
        self.sent.append(json.loads(payload))


@pytest.fixture
def bound_identity():
    token = None

    def bind(user_id: str, source: str = "plugin"):
        nonlocal token
        token = set_current_identity(Identity(user_id=user_id, scopes=("*",), source=source))

    yield bind
    if token is not None:
        reset_current_identity(token)


# ── L1: frame carries the stamped caller ──────────────────────────────────


def test_frame_carries_caller():
    runtime = get_default_runtime()
    peer = _FramePeer(runtime)
    inv = _edge_inv("u_alice")
    inv.peer = peer
    result = asyncio.run(EdgeToolExecutor(runtime, default_timeout=5).run(inv))
    assert result.status == "success"
    frame = peer.frames[0]
    assert frame["caller_user_id"] == "u_alice"
    # Caller travels OUTSIDE arguments — the model-controlled payload.
    assert CALLER_PARAM not in frame["arguments"]


def test_frame_omits_caller_when_unknown():
    runtime = get_default_runtime()
    peer = _FramePeer(runtime)
    inv = _edge_inv(None)
    inv.peer = peer
    asyncio.run(EdgeToolExecutor(runtime, default_timeout=5).run(inv))
    assert "caller_user_id" not in peer.frames[0]


# ── L1: caller derivation (identity unless internal, else session owner) ──


def test_effective_caller_prefers_authenticated_identity(bound_identity):
    bound_identity("u_real", source="plugin")
    assert effective_caller_user_id("u_owner") == "u_real"


def test_effective_caller_internal_falls_back_to_owner(bound_identity):
    bound_identity("system", source="internal")
    assert effective_caller_user_id("u_owner") == "u_owner"


def test_effective_caller_single_user_is_local():
    # No bound identity: the default provider yields the synthetic local user.
    assert effective_caller_user_id() == "_local"


def test_dispatcher_stamps_caller(monkeypatch, bound_identity):
    from yumi.core.platform.dispatch import dispatcher as dispatcher_mod
    from yumi.core.platform.dispatch.dispatcher import ToolDispatcher
    from yumi.core.platform.dispatch.local import LocalToolExecutor

    bound_identity("u_real", source="plugin")
    runtime = get_default_runtime()
    runtime.edge_registry.active_connections["dev"] = _FramePeer(runtime)
    monkeypatch.setattr(dispatcher_mod, "resolve_edge_for_prefixed_tool_name", lambda name, reg: "dev")

    d = ToolDispatcher(
        runtime,
        local_executor=LocalToolExecutor(timeout=5),
        edge_executor=EdgeToolExecutor(runtime, default_timeout=5),
    )
    ctx = TurnContext(prompt="hi", session_id="s1", owner_uid="u_owner")
    inv, event = d._resolve_edge_invocation("do", "edge_dev_do", "c1", {"x": 1}, ctx)
    assert event is None and inv is not None
    assert inv.caller_user_id == "u_real"

    runtime.edge_registry.active_connections.pop("dev", None)


# ── SDK: schema hides the reserved param ──────────────────────────────────


def test_schema_hides_caller_param():
    def create_item(title: str, caller_user_id: str) -> str:
        """Create an item.

        Args:
            title: The item title.
        """
        return "{}"

    schema = _build_tool_schema(create_item)
    params = schema["function"]["parameters"]
    assert CALLER_PARAM not in params["properties"]
    assert CALLER_PARAM not in params["required"]
    assert "title" in params["properties"]


# ── SDK: injection / fail-closed / anti-spoof ─────────────────────────────


def _agent_with(func, **register_kwargs) -> YumiAgent:
    agent = YumiAgent(edge_name="test-edge")
    agent.register(func, "test tool", **register_kwargs)
    return agent


def _call(agent: YumiAgent, msg: dict) -> dict:
    ws = _FakeWs()
    asyncio.run(agent._handle_tool_call(ws, msg))
    return ws.sent[0]


def test_sdk_injects_frame_caller():
    seen = {}

    def whoami(caller_user_id: str) -> str:
        seen["caller"] = caller_user_id
        return "done"

    agent = _agent_with(whoami)
    reply = _call(agent, {"name": "whoami", "arguments": {}, "call_id": "c1", "caller_user_id": "u_bob"})
    assert seen["caller"] == "u_bob"
    assert reply["result"] == "done"


def test_sdk_fails_closed_without_caller():
    def whoami(caller_user_id: str) -> str:
        raise AssertionError("must not execute without a caller")

    agent = _agent_with(whoami)
    reply = _call(agent, {"name": "whoami", "arguments": {}, "call_id": "c1"})
    assert "requires the caller's identity" in reply["result"]


def test_sdk_discards_caller_smuggled_into_arguments():
    seen = {}

    def whoami(caller_user_id: str) -> str:
        seen["caller"] = caller_user_id
        return "done"

    agent = _agent_with(whoami)
    _call(
        agent,
        {
            "name": "whoami",
            "arguments": {CALLER_PARAM: "u_attacker"},
            "call_id": "c1",
            "caller_user_id": "u_real",
        },
    )
    # The frame value wins; the argument-smuggled value is discarded.
    assert seen["caller"] == "u_real"


def test_sdk_strips_caller_for_tools_that_do_not_want_it():
    def plain(x: int) -> str:
        return str(x)

    agent = _agent_with(plain)
    reply = _call(
        agent,
        {
            "name": "plain",
            "arguments": {"x": 7, CALLER_PARAM: "u_attacker"},
            "call_id": "c1",
            "caller_user_id": "u_real",
        },
    )
    # No unexpected-kwarg crash; the smuggled key is simply dropped.
    assert reply["result"] == "7"
