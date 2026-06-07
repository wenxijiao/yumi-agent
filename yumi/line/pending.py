"""In-memory pending state for LINE postbacks (per process)."""

from __future__ import annotations

import asyncio
from typing import Any

PENDING_TOOL_CONFIRM: dict[str, asyncio.Future[str]] = {}
MODEL_PICK_SESSIONS: dict[str, list[str]] = {}
USAGE_PAGE_CTX: dict[str, str] = {}
TIMER_CARD_CTX: dict[str, dict[str, Any]] = {}


def register_timer_card_context(short_id: str, ctx: dict[str, Any]) -> None:
    TIMER_CARD_CTX[short_id] = ctx
