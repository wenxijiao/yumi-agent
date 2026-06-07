"""Chat and chat-debug HTTP routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from yumi.core.features.chat.debug_trace import (
    get_trace_path,
    start_trace,
    stop_trace,
)
from yumi.core.features.chat.debug_trace import (
    is_tracing as chat_debug_is_tracing,
)
from yumi.core.features.chat.pipeline import clear_session, generate_chat_events
from yumi.core.platform.http.dependencies import CurrentIdentity
from yumi.core.platform.http.schemas import ChatDebugRequest, ChatRequest
from yumi.core.platform.plugins import get_quota_policy, get_session_scope
from yumi.core.platform.runtime.accessors import stream_event
from yumi.core.platform.security.audit import audit_event

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
        # Tests monkey-patch ``yumi.core.features.chat.router.generate_chat_events``
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
