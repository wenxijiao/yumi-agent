"""Direct execution uses the same local/edge executors, without a model turn."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from copy import deepcopy
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field
from referencing import Registry
from referencing.exceptions import NoSuchResource
from yumi.core.platform.dispatch import EdgeToolExecutor, LocalToolExecutor, ToolDispatcher, TurnContext
from yumi.core.platform.http.dependencies import CurrentIdentity
from yumi.core.platform.plugins import get_session_scope, reset_current_identity, set_current_identity
from yumi.core.platform.runtime import get_default_runtime
from yumi.core.platform.runtime.assistant_context import conversation_session, source_channel
from yumi.core.platform.runtime.caller_context import reset_chat_owner_user_id, set_chat_owner_user_id
from yumi.core.platform.storage.tool_run_store import ToolRunStore

router = APIRouter()
_jobs: dict[str, asyncio.Task] = {}


def _store(identity):
    from yumi.core.features.assistant.router import _store as assistant_store

    return ToolRunStore(assistant_store(identity).sqlite, identity.user_id)


def _tool(identity, name):
    from yumi.core.features.assistant.router import visible_tools

    catalog = visible_tools(identity)
    tool = next(
        (t for t in catalog["server_tools"] + [t for d in catalog["devices"] for t in d["tools"]] if t["name"] == name),
        None,
    )
    if tool is None:
        raise HTTPException(404, "Tool not available to this account")
    return tool


def _available(tool):
    if tool["disabled"]:
        raise HTTPException(403, "Tool is disabled")
    if not tool["online"]:
        raise HTTPException(409, "Device is offline")


def validate_arguments(schema, arguments):
    schema = deepcopy(schema)
    schema.setdefault("additionalProperties", False)

    def no_remote(uri):
        raise NoSuchResource(ref=uri)

    try:
        Draft202012Validator.check_schema(schema)
        errors = list(Draft202012Validator(schema, registry=Registry(retrieve=no_remote)).iter_errors(arguments))
    except Exception as exc:
        raise HTTPException(422, "Tool parameter schema is not supported") from exc
    if errors:
        err = errors[0]
        path = ".".join(str(p) for p in err.absolute_path) or "arguments"
        # Avoid reflecting potentially secret argument values into error logs.
        raise HTTPException(422, f"Invalid {path}: {err.validator} constraint failed")
    if len(json.dumps(arguments)) > 64000:
        raise HTTPException(413, "Tool arguments are too large")


class RunRequest(BaseModel):
    arguments: dict = Field(default_factory=dict)
    request_id: UUID


class RunDecision(BaseModel):
    decision: Literal["allow", "deny"]


def _refresh(store, row):
    if (
        row
        and row["status"] in {"queued", "running", "awaiting_confirmation"}
        and row.get("expires_at", 0) < time.time()
    ):
        row, _ = store.transition(
            row["id"],
            {row["status"]},
            status="unknown" if row["status"] == "running" else "expired",
            result="Execution status is no longer available. Check the target before retrying.",
        )
    return row


def _launch(identity, row):
    task = asyncio.create_task(_execute(identity, row["id"]))
    _jobs[row["id"]] = task
    task.add_done_callback(lambda _: _jobs.pop(row["id"], None))


async def _execute(identity, run_id):
    from yumi.core.platform.storage.privacy_guard import lease

    with lease(identity.user_id):
        await _execute_leased(identity, run_id)


async def _execute_leased(identity, run_id):
    store = _store(identity)
    row, claimed = store.transition(run_id, {"queued"}, status="running", started_at_num=int(time.time() * 1000))
    if not claimed:
        return
    identity_token = set_current_identity(identity)
    owner_token = set_chat_owner_user_id(identity.user_id)
    sid_token = conversation_session.set(row["session_id"])
    channel_token = source_channel.set("app")
    started = time.monotonic()
    try:
        tool = _tool(identity, row["tool_name"])
        _available(tool)
        validate_arguments(tool["parameters"], row["arguments"])
        if tool["manual_require_confirmation"] and row.get("approval") != "confirmed":
            store.transition(run_id, {"running"}, status="awaiting_confirmation", expires_at=time.time() + 120)
            return
        runtime = get_default_runtime()
        dispatcher = ToolDispatcher(
            runtime,
            local_executor=LocalToolExecutor(timeout=30),
            edge_executor=EdgeToolExecutor(runtime, default_timeout=30),
        )
        ctx = TurnContext(prompt="", session_id=row["session_id"], owner_uid=identity.user_id)
        invocations, errors = dispatcher.prepare(
            [{"id": run_id, "function": {"name": row["tool_name"], "arguments": row["arguments"]}}], ctx
        )
        if errors or not invocations:
            raise HTTPException(409, "Tool or target device is unavailable")
        # Executing directly avoids inserting a synthetic LLM turn into chat.
        result = await asyncio.wait_for(dispatcher._run_one(invocations[0]), timeout=300)
        status = (
            "error"
            if result.status == "error" or str(result.result).lstrip().lower().startswith("error:")
            else "success"
        )
        store.transition(
            run_id,
            {"running"},
            status=status,
            result=str(result.result)[:32000],
            duration_ms=int((time.monotonic() - started) * 1000),
            steps=["parameters_validated", row.get("approval", "manual"), status],
        )
    except asyncio.CancelledError:
        store.transition(
            run_id, {"running"}, status="unknown", result="Execution interrupted; the operation may have completed."
        )
        raise
    except Exception as exc:
        message = str(exc.detail) if isinstance(exc, HTTPException) else "Tool execution failed or timed out."
        store.transition(
            run_id, {"running"}, status="error", result=message, duration_ms=int((time.monotonic() - started) * 1000)
        )
    finally:
        source_channel.reset(channel_token)
        conversation_session.reset(sid_token)
        reset_chat_owner_user_id(owner_token)
        reset_current_identity(identity_token)


@router.post("/tools/{name}/runs", status_code=202)
async def run_tool(name: str, body: RunRequest, identity: CurrentIdentity):
    from yumi.core.features.assistant.router import _qualify
    from yumi.core.features.assistant.router import _store as assistant_store

    tool = _tool(identity, name)
    _available(tool)
    validate_arguments(tool["parameters"], body.arguments)
    from yumi.core.features.assistant.personalization import preferences
    from yumi.core.platform.tools.presentation import render_action_summary

    locale = preferences(assistant_store(identity))["response_language"]
    action_summary = render_action_summary(
        tool.get("confirmation_template"), body.arguments, tool["parameters"], locale=locale
    )
    fingerprint = hashlib.sha256(json.dumps([name, body.arguments], sort_keys=True).encode()).hexdigest()
    state = assistant_store(identity).current(_qualify(identity))
    store = _store(identity)
    row, created = store.create(
        {
            "request_key": str(body.request_id),
            "fingerprint": fingerprint,
            "tool_name": name,
            "arguments": body.arguments,
            "action_summary": action_summary,
            "edge": tool.get("device"),
            "origin": "manual",
            "channel": "app",
            "session_id": state["session_id"],
            "status": "awaiting_confirmation" if tool["manual_require_confirmation"] else "queued",
            "approval": "pending" if tool["manual_require_confirmation"] else "manual",
            "result": "",
            "expires_at": time.time() + (120 if tool["manual_require_confirmation"] else 330),
            "steps": ["submitted"],
        }
    )
    if row["fingerprint"] != fingerprint:
        raise HTTPException(409, "Request id was already used with different parameters")
    if created and row["status"] == "queued":
        _launch(identity, row)
    return {"run": _refresh(store, row)}


@router.get("/tools/{name}/runs")
async def history(
    name: str, identity: CurrentIdentity, before: int | None = None, limit: int = Query(50, ge=1, le=100)
):
    _tool(identity, name)
    store = _store(identity)
    store.import_chat_history(name, get_session_scope())
    page = store.history(name, before, limit)
    page["runs"] = [_refresh(store, r) for r in page["runs"]]
    return page


@router.get("/tool-runs/{run_id}")
async def run_detail(run_id: str, identity: CurrentIdentity):
    store = _store(identity)
    row = _refresh(store, store.get(run_id))
    if row is None:
        raise HTTPException(404, "Run not found")
    return {"run": row}


@router.post("/tool-runs/{run_id}/decision")
async def decide(run_id: str, body: RunDecision, identity: CurrentIdentity):
    store = _store(identity)
    row = _refresh(store, store.get(run_id))
    if row is None:
        raise HTTPException(404, "Run not found")
    if row["origin"] != "manual":
        raise HTTPException(409, "This call must be confirmed in its conversation")
    if row["status"] != "awaiting_confirmation":
        return {"run": row}
    if body.decision == "allow":
        tool = _tool(identity, row["tool_name"])
        _available(tool)
        validate_arguments(tool["parameters"], row["arguments"])
    row, changed = store.transition(
        run_id,
        {"awaiting_confirmation"},
        status="queued" if body.decision == "allow" else "denied",
        approval="confirmed" if body.decision == "allow" else "denied",
        result="" if body.decision == "allow" else "You denied this invocation.",
        expires_at=time.time() + 330,
    )
    if changed and body.decision == "allow":
        _launch(identity, row)
    return {"run": row}
