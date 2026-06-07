"""Channel-handler abstraction for consuming the ``/chat`` NDJSON stream.

Background
----------
Every channel adapter (LINE bridge, Telegram bot, terminal CLI, web UI) used
to consume the chat stream by hand: an ``async for`` loop with a stringly-
typed ``if et == "text" / elif et == "tool_confirmation" / elif et == "error"``
ladder. Each block typically ran 25–30 lines, and identical blocks were
duplicated 4× inside ``yumi/line/handlers.py`` alone.

This module replaces that pattern with a Visitor:

* :class:`ChannelHandler` is a ``Protocol`` with one method per event type.
* :class:`BaseChannelHandler` provides no-op defaults so concrete handlers
  only override the events they care about.
* :func:`consume_chat_stream` walks any iterator of typed
  :class:`~yumi.core.platform.http.events.ChatEvent` models *or* plain dicts (parsed
  via :func:`~yumi.core.platform.http.events.parse_chat_event`) and dispatches each
  event to the right handler method.

Adding a new channel reduces to writing ~5 short methods. Adding a new event
type adds one method to ``ChannelHandler`` and one ``case`` here — every
existing channel keeps its no-op default until it explicitly opts in.
"""

from __future__ import annotations

from collections.abc import AsyncIterable
from typing import Protocol, runtime_checkable

from pydantic import BaseModel
from yumi.core.platform.http.events import (
    ErrorEvent,
    TextEvent,
    ThoughtEvent,
    ToolConfirmationEvent,
    ToolStatusEvent,
    parse_chat_event,
)


@runtime_checkable
class ChannelHandler(Protocol):
    """One consumer's policy for each event type in the chat stream."""

    async def on_text(self, event: TextEvent) -> None: ...
    async def on_thought(self, event: ThoughtEvent) -> None: ...
    async def on_tool_status(self, event: ToolStatusEvent) -> None: ...
    async def on_tool_confirmation(self, event: ToolConfirmationEvent) -> None: ...
    async def on_error(self, event: ErrorEvent) -> None: ...


class BaseChannelHandler:
    """No-op default implementation of :class:`ChannelHandler`.

    Subclasses override only the methods they need; everything else silently
    drops so a partial handler doesn't crash on an event type it doesn't yet
    know how to render.
    """

    async def on_text(self, event: TextEvent) -> None:
        return None

    async def on_thought(self, event: ThoughtEvent) -> None:
        return None

    async def on_tool_status(self, event: ToolStatusEvent) -> None:
        return None

    async def on_tool_confirmation(self, event: ToolConfirmationEvent) -> None:
        return None

    async def on_error(self, event: ErrorEvent) -> None:
        return None


async def consume_chat_stream(
    stream: AsyncIterable,
    handler: ChannelHandler,
) -> None:
    """Drive ``stream`` through ``handler``.

    ``stream`` may yield typed :class:`~yumi.core.platform.http.events.ChatEvent`
    models (preferred) or wire-format ``dict`` items. Dicts are validated
    into typed events before dispatch; an invalid dict surfaces as a
    ``ValidationError`` on the spot rather than silently dropping.
    """
    async for raw in stream:
        event = raw if isinstance(raw, BaseModel) else parse_chat_event(raw)
        kind = event.type
        if kind == "text":
            await handler.on_text(event)  # type: ignore[arg-type]
        elif kind == "thought":
            await handler.on_thought(event)  # type: ignore[arg-type]
        elif kind == "tool_status":
            await handler.on_tool_status(event)  # type: ignore[arg-type]
        elif kind == "tool_confirmation":
            await handler.on_tool_confirmation(event)  # type: ignore[arg-type]
        elif kind == "error":
            await handler.on_error(event)  # type: ignore[arg-type]
        # Unknown ``type`` would have failed in ``parse_chat_event`` already.


__all__ = [
    "BaseChannelHandler",
    "ChannelHandler",
    "consume_chat_stream",
]
