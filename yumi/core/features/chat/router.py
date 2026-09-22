"""Chat streaming and durable turn-detail HTTP routes."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from yumi.core.features.chat.pipeline import clear_session, generate_chat_events
from yumi.core.platform.http.dependencies import CurrentIdentity
from yumi.core.platform.http.schemas import ChatRequest
from yumi.core.platform.observability.turn_inspector import get_turn, list_turns
from yumi.core.platform.plugins import get_memory_factory, get_quota_policy, get_session_scope
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
    store = None
    if body.personal:
        from yumi.core.platform.storage.assistant_store import AssistantStore

        store = AssistantStore(get_memory_factory().get_for_identity(identity).sqlite, identity.user_id)
        current = store.current(lambda value: get_session_scope().qualify_session_http(identity, value))
        if body.revision is not None and body.revision != current["revision"]:
            raise HTTPException(409, "Conversation changed. Refresh before sending.")
        sid = current["session_id"]
    media_store = None
    if body.voice_id or body.reply_voice:
        from yumi.core.platform.storage.voice_store import VoiceStore

        media_store = VoiceStore(get_memory_factory().get_for_identity(identity).sqlite, identity.user_id)
    if body.voice_id:
        assert media_store is not None
        voice = media_store.get(body.voice_id)
        if voice["kind"] != "user" or voice["session_id"] != sid or not voice["transcript"]:
            raise HTTPException(409, "Recording does not belong to this conversation.")
        if voice["event_id"]:
            raise HTTPException(409, "This voice message has already been sent.")
        body.prompt = voice["transcript"]
    audit_event("chat_request", identity.user_id, session_id=sid)

    async def generate():
        from yumi.core.platform.runtime.assistant_context import active_requests, message_media, source_channel

        task = asyncio.current_task()
        token = source_channel.set(body.channel if body.personal else None)
        active_requests.setdefault(sid, set()).add(task)
        media_token = None
        claimed = False
        try:
            voice = media_store.claim(body.voice_id, sid) if body.voice_id and media_store else None
            claimed = voice is not None
            media_token = message_media.set(
                {"input": media_store.summary(voice) if voice and media_store else None, "reply": body.reply_voice}
            )
            if store and store.get("state")["session_id"] != sid:
                yield stream_event(
                    "error", code="CONTEXT_CHANGED", content="Conversation restarted. Please send again."
                )
                return
            charged = False
            async for event in generate_chat_events(body.prompt, sid, think=body.think):
                if store and store.get("state")["session_id"] != sid:
                    yield stream_event("error", code="CONTEXT_CHANGED", content="Conversation restarted.")
                    return
                if not charged and event.get("type") != "error":
                    quota.record_chat_turn(identity)
                    charged = True
                yield stream_event(event["type"], **{k: v for k, v in event.items() if k != "type"})
        except HTTPException as exc:
            yield stream_event("error", code=str(exc.status_code), content=str(exc.detail))
        finally:
            if media_token is not None:
                message_media.reset(media_token)
            if claimed and media_store:
                media_store.release(body.voice_id)
            source_channel.reset(token)
            active_requests.get(sid, set()).discard(task)
            if not active_requests.get(sid):
                active_requests.pop(sid, None)

    return StreamingResponse(generate(), media_type="application/x-ndjson")


@router.post("/clear")
async def clear_endpoint(identity: CurrentIdentity, session_id: str = "default"):
    sid = get_session_scope().qualify_session_http(identity, session_id)
    return await clear_session(sid)


@router.get("/chat/turns")
async def list_chat_turns_endpoint(
    identity: CurrentIdentity,
    session_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
):
    """List durable execution summaries, with a live running turn overlay."""
    scope = get_session_scope()
    sid = scope.qualify_session_http(identity, session_id) if session_id else None
    sqlite = get_memory_factory().get_for_identity(identity).sqlite
    durable = sqlite.list_turn_traces(
        session_id=sid,
        owner_user_id=identity.user_id,
        limit=limit,
    )
    live = list_turns(session_id=sid, limit=limit)
    merged = {str(row.get("id") or ""): row for row in durable}
    for row in live:
        if row.get("owner_user_id") in (None, "", identity.user_id):
            merged[str(row.get("id") or "")] = row
    rows = sorted(merged.values(), key=lambda row: str(row.get("started_at") or ""), reverse=True)[:limit]
    return {"turns": rows, "retention": {"kind": "durable", "message": "Saved with conversation history."}}


@router.get("/chat/turns/{turn_id}")
async def get_chat_turn_endpoint(identity: CurrentIdentity, turn_id: str):
    """Return one complete execution trace after enforcing session ownership."""
    sqlite = get_memory_factory().get_for_identity(identity).sqlite
    turn = get_turn(turn_id) or sqlite.get_turn_trace(turn_id)
    if turn is None:
        raise HTTPException(status_code=404, detail="Turn not found.")
    get_session_scope().ensure_session_owned_by_identity(identity, str(turn.get("session_id") or ""))
    return {"turn": turn}


@router.get("/chat/turns/{turn_id}/activity")
async def get_chat_turn_activity(identity: CurrentIdentity, turn_id: str):
    from yumi.core.platform.storage.assistant_store import AssistantStore

    sqlite = get_memory_factory().get_for_identity(identity).sqlite
    trace = get_turn(turn_id) or sqlite.get_turn_trace(turn_id)
    if trace is None:
        raise HTTPException(404, "Turn not found.")
    get_session_scope().ensure_session_owned_by_identity(identity, str(trace.get("session_id") or ""))
    return AssistantStore(sqlite, identity.user_id).turn_activity(trace)


class ClientTiming(BaseModel):
    model_config = ConfigDict(extra="forbid")
    input_ready_ms: int | None = Field(default=None, ge=0, le=86400000)
    first_text_ms: int | None = Field(default=None, ge=0, le=86400000)
    text_done_ms: int | None = Field(default=None, ge=0, le=86400000)
    first_audio_ms: int | None = Field(default=None, ge=0, le=86400000)
    audio_done_ms: int | None = Field(default=None, ge=0, le=86400000)


@router.post("/chat/turns/{turn_id}/timing")
async def record_client_timing(identity: CurrentIdentity, turn_id: str, body: ClientTiming):
    """Owner-reported elapsed times; never mixed with trusted server durations."""
    sqlite = get_memory_factory().get_for_identity(identity).sqlite
    with sqlite.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT session_id,detail_json,summary_json FROM turn_traces WHERE turn_id=?", (turn_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Turn not found.")
        get_session_scope().ensure_session_owned_by_identity(identity, row["session_id"])
        detail, summary = json.loads(row["detail_json"]), json.loads(row["summary_json"])
        # First observation wins: replay must not rewrite initial response latency.
        timing = detail.setdefault("client_timing", {})
        for name, value in body.model_dump(exclude_none=True).items():
            timing.setdefault(name, value)
        summary["client_timing"] = timing
        conn.execute(
            "UPDATE turn_traces SET detail_json=?,summary_json=? WHERE turn_id=?",
            (json.dumps(detail), json.dumps(summary), turn_id),
        )
    return {"ok": True}
