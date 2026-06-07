"""Public entry points for the ``/chat`` HTTP route and timer callbacks.

The implementation lives in ``kumi.core.features.chat.service``. This module
keeps the historical ``generate_chat_events`` / ``clear_session`` API stable
for the three call sites:

* ``kumi.core.api.routers.chat`` (the HTTP endpoint),
* ``kumi.core.api.timers`` (timer-fired follow-up turns),
* ``kumi.line.handlers`` (LINE direct-mode bridge).

Internally the orchestrator now yields :class:`~kumi.core.platform.http.events.ChatEvent`
models for type safety; this façade serialises each event to ``dict`` at the
public boundary so existing dict-shaped consumers keep working unchanged.
External consumers that want the typed surface should import
:mod:`kumi.core.platform.http.events` and use :func:`parse_chat_event` (or migrate to
the channel-handler pattern in :mod:`kumi.core.platform.http.stream_consumer`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from kumi.core.api.state import SESSION_LOCKS
from kumi.core.features.chat.service import ChatTurnService
from kumi.core.platform.http.events import ChatEvent
from kumi.core.platform.plugins import get_bot_pool, get_session_scope


async def generate_chat_events(
    prompt: str,
    session_id: str,
    think: bool = False,
    *,
    timer_callback: bool = False,
) -> AsyncIterator[dict]:
    """Stream chat-turn events for ``session_id`` as wire-format ``dict``s.

    Yields dicts shaped like ``{"type": "text"|"thought"|"tool_status"|...}``.
    Tests substitute this function via ``monkeypatch.setattr`` on the
    importing module (``kumi.core.api.routers.chat`` for the HTTP layer).
    """
    async for event in stream_chat_events(prompt, session_id, think=think, timer_callback=timer_callback):
        yield event.model_dump()


async def stream_chat_events(
    prompt: str,
    session_id: str,
    think: bool = False,
    *,
    timer_callback: bool = False,
) -> AsyncIterator[ChatEvent]:
    """Typed twin of :func:`generate_chat_events` — yields :class:`ChatEvent` models.

    Use this from new code; the legacy dict-shaped function is kept for
    backward compatibility with consumers that haven't migrated yet.
    """
    async for event in ChatTurnService().stream_chat_turn(
        prompt,
        session_id,
        think=think,
        timer_callback=timer_callback,
    ):
        yield event


async def clear_session(session_id: str) -> dict:
    """Reset memory for ``session_id`` and drop its session lock entry."""
    owner = get_session_scope().owner_user_from_session_id(session_id)
    bot = await get_bot_pool().get_bot_for_session_owner(owner)
    bot.clear_memory(session_id)
    # Only drop the lock if it isn't held — otherwise an in-flight chat turn
    # is using it and a concurrent next-turn would create a fresh lock,
    # letting two turns mutate ephemeral_messages / memory at once.
    lock = SESSION_LOCKS.get(session_id)
    if lock is not None and not lock.locked():
        SESSION_LOCKS.pop(session_id, None)
    return {"status": "success", "message": f"Cleared memory for session: {session_id}"}
