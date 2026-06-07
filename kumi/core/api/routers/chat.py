"""Chat and chat-debug HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from kumi.core.api.chat import clear_session, generate_chat_events
from kumi.core.api.chat_debug_trace import (
    get_trace_path,
    start_trace,
    stop_trace,
)
from kumi.core.api.chat_debug_trace import (
    is_tracing as chat_debug_is_tracing,
)
from kumi.core.api.dependencies import CurrentIdentity
from kumi.core.api.schemas import ChatDebugRequest, ChatRequest
from kumi.core.api.state import stream_event
from kumi.core.audit import audit_event
from kumi.core.plugins import get_quota_policy, get_session_scope

router = APIRouter()


@router.post("/chat")
async def chat_endpoint(request: Request, identity: CurrentIdentity, body: ChatRequest):
    quota = get_quota_policy()
    allowed, qerr = quota.check_chat_allowed(identity)
    if not allowed:
        raise HTTPException(status_code=429, detail=qerr)
    tok_ok, tok_err = quota.check_token_quota(identity)
    if not tok_ok:
        raise HTTPException(status_code=429, detail=tok_err)
    sid = get_session_scope().qualify_session_http(identity, body.session_id)
    quota.record_chat_turn(identity)
    audit_event("chat_request", identity.user_id, session_id=sid)

    async def generate():
        # Tests monkey-patch ``kumi.core.api.routers.chat.generate_chat_events``
        # to substitute a fake generator. The lookup happens here (via module
        # globals) so the patch is honored on every request.
        async for event in generate_chat_events(body.prompt, sid, think=body.think):
            yield stream_event(event["type"], **{k: v for k, v in event.items() if k != "type"})

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@router.post("/clear")
async def clear_endpoint(identity: CurrentIdentity, session_id: str = "default"):
    sid = get_session_scope().qualify_session_http(identity, session_id)
    return await clear_session(sid)


@router.put("/config/chat-debug")
async def put_chat_debug_endpoint(identity: CurrentIdentity, body: ChatDebugRequest):
    sid = get_session_scope().qualify_session_http(identity, body.session_id)
    if body.enabled:
        path = start_trace(sid)
        return {"status": "success", "enabled": True, "trace_path": path}
    path = stop_trace(sid)
    return {"status": "success", "enabled": False, "trace_path": path or ""}


@router.get("/config/chat-debug")
async def get_chat_debug_endpoint(identity: CurrentIdentity, session_id: str = "default"):
    sid = get_session_scope().qualify_session_http(identity, session_id)
    p = get_trace_path(sid)
    return {"enabled": chat_debug_is_tracing(sid), "trace_path": p or ""}
