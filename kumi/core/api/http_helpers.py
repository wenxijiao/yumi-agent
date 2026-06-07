"""Shared HTTP helpers for FastAPI routes."""

from fastapi import HTTPException
from kumi.core.config import DEFAULT_SYSTEM_PROMPT, get_system_prompt
from kumi.core.platform.plugins import get_current_identity, get_memory_factory


def get_system_prompt_payload():
    system_prompt = get_system_prompt()
    return {
        "system_prompt": system_prompt,
        "is_default": system_prompt == DEFAULT_SYSTEM_PROMPT,
    }


def get_session_payload(session_id: str):
    mem = get_memory_factory().get_for_identity(get_current_identity())
    session = mem.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found.")
    return session
