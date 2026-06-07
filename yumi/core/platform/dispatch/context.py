"""Turn-scoped state container and tool-invocation value objects.

Replaces the dozen-or-so closure variables that used to live inside
``_generate_chat_events_impl``. Keeping per-turn mutable state in one place
makes each collaborator (normalizer, gate, dispatcher, sink) trivially
unit-testable: pass a context, observe the new state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TurnContext:
    """Mutable state for a single ``/chat`` turn.

    Long-lived only for the duration of one ``generate_chat_events`` call.
    Not thread-safe — turns are serialized per-session by ``SessionLockRegistry``.
    """

    prompt: str
    session_id: str
    think: bool = False
    timer_callback: bool = False
    owner_uid: str | None = None

    loop_count: int = 0
    ephemeral_messages: list[dict] = field(default_factory=list)
    active_edge_tool_names: set[str] = field(default_factory=set)
    tool_loop_events: list[dict] = field(default_factory=list)
    last_tools: list | None = None

    # Tracks consecutive normalization failures so we can bail out cleanly.
    tool_format_retries: int = 0


@dataclass
class ToolInvocation:
    """A single tool the model asked to call, after argument parsing.

    ``kind`` is ``"local"`` or ``"edge"``. ``peer`` and ``target_edge`` are
    populated only for edge invocations.
    """

    kind: str
    func_name: str
    tool_message_name: str
    args: dict
    target_edge: str | None = None
    original_tool_name: str | None = None
    peer: Any | None = None


@dataclass
class ToolResult:
    """Outcome of running one ``ToolInvocation``."""

    func_name: str
    result: str
    status: str  # "success" | "error"
    original_tool_name: str | None = None
    target_edge: str | None = None

    @property
    def display_label(self) -> str:
        if self.original_tool_name and self.target_edge:
            return f"'{self.original_tool_name}' on '{self.target_edge}'"
        return f"'{self.func_name}'"
