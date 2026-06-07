"""Memory session and message routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query
from yumi.core.features.memory.store import get_memory_store_for_identity
from yumi.core.platform.http.dependencies import CurrentIdentity
from yumi.core.platform.http.schemas import (
    MemoryCreateRequest,
    MemoryUpdateRequest,
    SessionCreateRequest,
    SessionUpdateRequest,
)
from yumi.core.platform.plugins import get_session_scope

router = APIRouter()


@router.get("/memory/sessions")
async def list_memory_sessions_endpoint(identity: CurrentIdentity, status: str = Query(default="active")):
    prefix = get_session_scope().session_id_prefix_for_identity(identity)
    try:
        sessions = get_memory_store_for_identity(identity).list_sessions(status=status, session_id_prefix=prefix)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"sessions": sessions}


@router.post("/memory/sessions")
async def create_memory_session_endpoint(
    identity: CurrentIdentity,
    request: SessionCreateRequest | None = None,
):
    new_id = get_session_scope().qualify_session_http(identity, str(uuid.uuid4()))
    session = get_memory_store_for_identity(identity).create_session(
        title=request.title if request else None, session_id=new_id
    )
    return {"status": "success", "session": session}


@router.get("/memory/sessions/{session_id}")
async def get_memory_session_endpoint(identity: CurrentIdentity, session_id: str):
    sid = get_session_scope().qualify_session_http(identity, session_id)
    mem = get_memory_store_for_identity(identity)
    session = mem.get_session(sid)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return session


@router.put("/memory/sessions/{session_id}")
async def update_memory_session_endpoint(identity: CurrentIdentity, session_id: str, request: SessionUpdateRequest):
    sid = get_session_scope().qualify_session_http(identity, session_id)
    try:
        session = get_memory_store_for_identity(identity).update_session(
            session_id=sid,
            title=request.title,
            is_pinned=request.is_pinned,
            status=request.status,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return {"status": "success", "session": session}


@router.get("/memory/messages")
async def list_memory_messages_endpoint(
    identity: CurrentIdentity,
    session_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    scope = get_session_scope()
    sid = scope.qualify_session_http(identity, session_id) if session_id else None
    return {
        "messages": get_memory_store_for_identity(identity).list_messages(
            session_id=sid,
            limit=limit,
            offset=offset,
        )
    }


@router.get("/memory/messages/{message_id}")
async def get_memory_message_endpoint(identity: CurrentIdentity, message_id: str):
    message = get_memory_store_for_identity(identity).get_message(message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Memory message not found.")
    get_session_scope().ensure_message_owned_by_identity(identity, message)
    return message


@router.post("/memory/messages")
async def create_memory_message_endpoint(identity: CurrentIdentity, request: MemoryCreateRequest):
    sid = get_session_scope().qualify_session_http(identity, request.session_id)
    try:
        message = get_memory_store_for_identity(identity).create_message(
            session_id=sid,
            role=request.role,
            content=request.content,
            thought=request.thought,
        )
    except ValueError as exc:
        if "memory_quota_exceeded" in str(exc):
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "success", "message": message}


@router.put("/memory/messages/{message_id}")
async def update_memory_message_endpoint(identity: CurrentIdentity, message_id: str, request: MemoryUpdateRequest):
    existing = get_memory_store_for_identity(identity).get_message(message_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Memory message not found.")
    get_session_scope().ensure_message_owned_by_identity(identity, existing)
    try:
        message = get_memory_store_for_identity(identity).update_message(
            message_id=message_id,
            content=request.content,
            role=request.role,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if message is None:
        raise HTTPException(status_code=404, detail="Memory message not found.")
    return {"status": "success", "message": message}


@router.delete("/memory/messages/{message_id}")
async def delete_memory_message_endpoint(identity: CurrentIdentity, message_id: str):
    existing = get_memory_store_for_identity(identity).get_message(message_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Memory message not found.")
    get_session_scope().ensure_message_owned_by_identity(identity, existing)
    deleted = get_memory_store_for_identity(identity).delete_message(message_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory message not found.")
    return {"status": "success", "message_id": message_id}


@router.get("/memory/search")
async def search_memory_endpoint(
    identity: CurrentIdentity,
    query: str,
    session_id: str | None = None,
    limit: int = Query(default=10, ge=1, le=100),
):
    scope = get_session_scope()
    sid = scope.qualify_session_http(identity, session_id) if session_id else None
    return {
        "messages": get_memory_store_for_identity(identity).search_messages(
            query=query,
            session_id=sid,
            limit=limit,
        )
    }
