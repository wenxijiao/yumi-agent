"""Typed schema for the ``/chat`` NDJSON event stream.

Background
----------
``POST /chat`` returns ``application/x-ndjson``. Each line is a JSON object
keyed by ``type`` — ``text`` / ``thought`` / ``tool_status`` /
``tool_confirmation`` / ``error``. Until now the schema lived in prose in
``docs/HTTP_API.md`` and as ad-hoc ``dict`` literals at every emit site.
Consumers (LINE / Telegram / SDK / web UI / enterprise relay) each parsed
the dicts via stringly-typed branches; new event types could silently slip
through.

This module replaces the convention with a Pydantic *discriminated union*
keyed by ``type``. Producers construct typed instances; consumers can opt
into ``isinstance`` / ``match`` dispatch (see :mod:`kumi.core.api.stream_consumer`).
External callers that still want plain dicts get them via ``model_dump`` at
the public boundary in :mod:`kumi.core.api.chat`.

The wire format is unchanged — ``model_dump()`` + ``json.dumps`` produces
exactly the same JSON the legacy code did, so HTTP clients see no difference.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

# Common base; extra="allow" keeps us compatible with any historical fields
# that may surface from older servers but aren't yet declared here.
_BaseConfig = ConfigDict(extra="allow")


class TextEvent(BaseModel):
    """Streamed model text chunk."""

    model_config = _BaseConfig
    type: Literal["text"] = "text"
    content: str


class ThoughtEvent(BaseModel):
    """Reasoning / thought chunk, only emitted when ``think=True``."""

    model_config = _BaseConfig
    type: Literal["thought"] = "thought"
    content: str


class ToolStatusEvent(BaseModel):
    """Lifecycle marker for one tool invocation.

    ``status`` follows the legacy alphabet: ``running`` while the tool is
    executing, ``success`` / ``error`` after it returns. ``denied`` is used
    when the user rejects a confirmation.
    """

    model_config = _BaseConfig
    type: Literal["tool_status"] = "tool_status"
    status: Literal["running", "success", "error", "denied"]
    content: str


class ToolConfirmationEvent(BaseModel):
    """Tool call awaiting user approval.

    The client must POST ``/tools/confirm`` with the same ``call_id`` (or the
    confirmation times out and is treated as ``deny``).
    """

    model_config = _BaseConfig
    type: Literal["tool_confirmation"] = "tool_confirmation"
    call_id: str
    tool_name: str
    full_tool_name: str
    arguments: dict


class ErrorEvent(BaseModel):
    """Pipeline-level failure.

    ``code`` is a stable machine-readable identifier when known (e.g.
    ``KUMI_CHAT_PIPELINE_FAILED``); ``content`` is a human-friendly message.
    """

    model_config = _BaseConfig
    type: Literal["error"] = "error"
    content: str
    code: str | None = None


ChatEvent = Annotated[
    Union[
        TextEvent,
        ThoughtEvent,
        ToolStatusEvent,
        ToolConfirmationEvent,
        ErrorEvent,
    ],
    Field(discriminator="type"),
]
"""Tagged union over every public ``/chat`` stream event."""


_chat_event_adapter: TypeAdapter[ChatEvent] = TypeAdapter(ChatEvent)


def parse_chat_event(payload: dict | str | bytes) -> ChatEvent:
    """Validate ``payload`` (one NDJSON line / one dict) into a typed event."""
    if isinstance(payload, (str, bytes)):
        return _chat_event_adapter.validate_json(payload)
    return _chat_event_adapter.validate_python(payload)


def serialize_chat_event(event: ChatEvent) -> str:
    """Encode ``event`` as one NDJSON line (terminating ``\\n`` included)."""
    return event.model_dump_json() + "\n"


__all__ = [
    "ChatEvent",
    "ErrorEvent",
    "TextEvent",
    "ThoughtEvent",
    "ToolConfirmationEvent",
    "ToolStatusEvent",
    "parse_chat_event",
    "serialize_chat_event",
]
