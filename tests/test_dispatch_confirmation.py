"""ConfirmationGate: bypass when always-allowed, deny on user reject, deny on timeout."""

from __future__ import annotations

import asyncio

import pytest
from yumi.core.platform.dispatch.confirmation import ConfirmationGate
from yumi.core.platform.dispatch.context import ToolInvocation, TurnContext
from yumi.core.platform.runtime import get_default_runtime


def _ctx() -> TurnContext:
    return TurnContext(prompt="hi", session_id="s1")


def _local_inv(name: str = "do_thing") -> ToolInvocation:
    return ToolInvocation(kind="local", func_name=name, tool_message_name=name, args={})


@pytest.fixture
def gate_and_runtime():
    runtime = get_default_runtime()
    runtime.tool_policy.confirmation_tools.clear()
    runtime.tool_policy.always_allowed_tools.clear()
    runtime.tool_policy.pending_confirmations.clear()
    return ConfirmationGate(runtime), runtime


async def _drain(gen) -> list:
    out = []
    async for item in gen:
        out.append(item)
    return out


def test_no_confirmation_required_passes_through(gate_and_runtime):
    gate, _ = gate_and_runtime
    inv = _local_inv()
    out = asyncio.run(_drain(gate.filter([inv], _ctx())))
    assert out == [(None, inv)]


def test_always_allowed_skips_prompt(gate_and_runtime):
    gate, runtime = gate_and_runtime
    inv = _local_inv()
    runtime.tool_policy.confirmation_tools.add(inv.func_name)
    runtime.tool_policy.always_allowed_tools.add(inv.func_name)
    out = asyncio.run(_drain(gate.filter([inv], _ctx())))
    assert out == [(None, inv)]


def test_user_deny_blocks_invocation(gate_and_runtime):
    gate, runtime = gate_and_runtime
    inv = _local_inv()
    runtime.tool_policy.confirmation_tools.add(inv.func_name)
    ctx = _ctx()

    async def scenario():
        agen = gate.filter([inv], ctx)
        first = await agen.__anext__()
        assert first[0] is not None and first[0].type == "tool_confirmation"
        # Resolve the future to "deny" using the call_id assigned by the gate.
        confirm_id = first[0].call_id
        runtime.tool_policy.pending_confirmations[confirm_id].set_result("deny")
        rest = []
        async for ev in agen:
            rest.append(ev)
        return rest

    rest = asyncio.run(scenario())
    # After deny: a ToolStatusEvent is emitted, no invocation is yielded.
    assert any(ev[0] is not None and ev[0].status == "error" for ev in rest)
    assert all(ev[1] is None for ev in rest)
    assert ctx.ephemeral_messages[-1]["content"] == "Tool execution was denied by the user."


def test_user_approve_yields_invocation(gate_and_runtime):
    gate, runtime = gate_and_runtime
    inv = _local_inv()
    runtime.tool_policy.confirmation_tools.add(inv.func_name)

    async def scenario():
        agen = gate.filter([inv], _ctx())
        first = await agen.__anext__()
        confirm_id = first[0].call_id
        runtime.tool_policy.pending_confirmations[confirm_id].set_result("allow")
        rest = []
        async for ev in agen:
            rest.append(ev)
        return rest

    rest = asyncio.run(scenario())
    assert rest == [(None, inv)]


def test_always_allow_persists_policy(gate_and_runtime, monkeypatch):
    gate, runtime = gate_and_runtime
    inv = _local_inv("write_file")
    runtime.tool_policy.confirmation_tools.add(inv.func_name)

    persisted = []

    def fake_persist():
        persisted.append(True)

    import yumi.core.features.edge.api as api_edge

    monkeypatch.setattr(api_edge, "persist_local_tool_confirmation_to_config", fake_persist)

    async def scenario():
        agen = gate.filter([inv], _ctx())
        first = await agen.__anext__()
        confirm_id = first[0].call_id
        runtime.tool_policy.pending_confirmations[confirm_id].set_result("always_allow")
        async for _ in agen:
            pass

    asyncio.run(scenario())
    assert inv.func_name in runtime.tool_policy.always_allowed_tools
    assert inv.func_name not in runtime.tool_policy.confirmation_tools
    assert persisted == [True]
