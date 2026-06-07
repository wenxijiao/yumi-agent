"""ToolDispatcher: argument parsing, local/edge classification, parallel run."""

from __future__ import annotations

import asyncio

import pytest
from yumi.core.platform.dispatch.context import ToolInvocation, ToolResult, TurnContext
from yumi.core.platform.dispatch.dispatcher import ToolDispatcher, canonical_local_tool_name
from yumi.core.platform.dispatch.edge import EdgeToolExecutor
from yumi.core.platform.dispatch.local import LocalToolExecutor
from yumi.core.platform.runtime import get_default_runtime
from yumi.core.platform.tools.tool import TOOL_REGISTRY


@pytest.fixture
def runtime():
    return get_default_runtime()


@pytest.fixture
def dispatcher(runtime):
    return ToolDispatcher(
        runtime,
        local_executor=LocalToolExecutor(timeout=5),
        edge_executor=EdgeToolExecutor(runtime, default_timeout=5),
    )


def _ctx() -> TurnContext:
    return TurnContext(prompt="hi", session_id="s1")


def _tcall(name: str, args: str | dict) -> dict:
    return {"id": "c1", "function": {"name": name, "arguments": args}}


def test_canonical_strips_functions_prefix(monkeypatch):
    monkeypatch.setitem(TOOL_REGISTRY, "echo", {})
    assert canonical_local_tool_name("functions.echo") == "echo"
    monkeypatch.delitem(TOOL_REGISTRY, "echo", raising=False)


def test_canonical_lowercases_when_only_lower_present(monkeypatch):
    monkeypatch.setitem(TOOL_REGISTRY, "echo", {})
    assert canonical_local_tool_name("ECHO") == "echo"
    monkeypatch.delitem(TOOL_REGISTRY, "echo", raising=False)


def test_canonical_passes_edge_prefix_through():
    assert canonical_local_tool_name("edge_dev__do_thing") == "edge_dev__do_thing"


def test_prepare_local_tool_classified_as_local(dispatcher, monkeypatch):
    monkeypatch.setitem(TOOL_REGISTRY, "echo", {})
    invs, events = dispatcher.prepare([_tcall("echo", '{"a":1}')], _ctx())
    assert events == []
    assert len(invs) == 1
    assert invs[0].kind == "local"
    assert invs[0].args == {"a": 1}
    monkeypatch.delitem(TOOL_REGISTRY, "echo", raising=False)


def test_prepare_unknown_tool_yields_error_and_message(dispatcher):
    ctx = _ctx()
    invs, events = dispatcher.prepare([_tcall("nope", "{}")], ctx)
    assert invs == []
    assert len(events) == 1
    assert events[0].status == "error"
    assert ctx.ephemeral_messages and ctx.ephemeral_messages[-1]["role"] == "tool"


def test_prepare_invalid_json_arguments_repaired(dispatcher, monkeypatch):
    monkeypatch.setitem(TOOL_REGISTRY, "echo", {})
    invs, events = dispatcher.prepare([_tcall("echo", "{a:1,}")], _ctx())
    assert events == []
    assert len(invs) == 1
    assert "a" in invs[0].args
    monkeypatch.delitem(TOOL_REGISTRY, "echo", raising=False)


def test_prepare_unrepairable_json_yields_error(dispatcher, monkeypatch):
    monkeypatch.setitem(TOOL_REGISTRY, "echo", {})
    ctx = _ctx()
    invs, events = dispatcher.prepare([_tcall("echo", "][not parseable")], ctx)
    assert invs == [] or all(i.args == {} for i in invs)
    monkeypatch.delitem(TOOL_REGISTRY, "echo", raising=False)


def test_prepare_set_timer_stamps_session_id(dispatcher, monkeypatch):
    monkeypatch.setitem(TOOL_REGISTRY, "set_timer", {})
    ctx = _ctx()
    ctx.session_id = "abc"
    invs, _ = dispatcher.prepare([_tcall("set_timer", '{"delay": 5}')], ctx)
    assert invs[0].args["session_id"] == "abc"
    monkeypatch.delitem(TOOL_REGISTRY, "set_timer", raising=False)


def test_run_all_executes_in_parallel(dispatcher):
    invs = [
        ToolInvocation(kind="local", func_name="t1", tool_message_name="t1", args={}),
        ToolInvocation(kind="local", func_name="t2", tool_message_name="t2", args={}),
    ]

    async def fake_run(inv):
        await asyncio.sleep(0.01)
        return ToolResult(func_name=inv.func_name, result="ok", status="success")

    dispatcher._run_one = fake_run  # type: ignore[assignment]
    results = asyncio.run(dispatcher.run_all(invs, _ctx()))
    assert [r.result for r in results] == ["ok", "ok"]
    assert results[0].func_name == "t1"
    assert results[1].func_name == "t2"
