"""Per-request owner for tools (timers) — set during chat generation."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from yumi.core.platform.plugins import SINGLE_USER_ID

_chat_owner_user_id: ContextVar[str | None] = ContextVar("yumi_chat_owner_user_id", default=None)


def set_chat_owner_user_id(user_id: str) -> Any:
    return _chat_owner_user_id.set(user_id)


def reset_chat_owner_user_id(token: Any) -> None:
    _chat_owner_user_id.reset(token)


def get_chat_owner_user_id() -> str:
    return _chat_owner_user_id.get() or SINGLE_USER_ID
