"""Turn-scoped state container and tool-invocation value objects.

Replaces the dozen-or-so closure variables that used to live inside
``_generate_chat_events_impl``. Keeping per-turn mutable state in one place
makes each collaborator (normalizer, gate, dispatcher, sink) trivially
unit-testable: pass a context, observe the new state.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from yumi.core.platform.runtime.assistant_context import PromptSnapshot


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
    turn_id: str = field(default_factory=lambda: uuid4().hex)

    prompt_snapshot: PromptSnapshot = field(default_factory=PromptSnapshot)
    tools_stopped_reason: str | None = None
    closing_requested: bool = False
    loop_count: int = 0
    ephemeral_messages: list[dict] = field(default_factory=list)
    active_edge_tool_names: set[str] = field(default_factory=set)
    recent_discovered_tools: list[str] = field(default_factory=list)
    tool_loop_events: list[dict] = field(default_factory=list)
    last_tools: list | None = None
    routing_summary: dict[str, Any] = field(default_factory=dict)

    # How long each tool took and whether it succeeded, keyed by tool_call_id.
    # Kept beside the messages rather than on them: tool messages are forwarded
    # to the provider verbatim (see ``openai_provider._ensure_tool_call_ids``),
    # and an unknown field there is a 400 from a strict endpoint. The transcript
    # writer folds these in when it copies messages for persistence.
    tool_metrics: dict[str, dict] = field(default_factory=dict)

    # Tracks consecutive normalization failures so we can bail out cleanly.
    tool_format_retries: int = 0
    tool_call_ids: set[str] = field(default_factory=set)

    # Capture before waiting for another channel's turn to release the lock.
    request_started: float = field(default_factory=time.perf_counter)
    request_started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


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
    tool_call_id: str = ""
    target_edge: str | None = None
    original_tool_name: str | None = None
    peer: Any | None = None
    # Authenticated principal this call runs on behalf of (server-derived,
    # never model-supplied). Sent to edges as the ``caller_user_id`` frame
    # field so a shared edge can scope its work to the caller.
    caller_user_id: str | None = None
    approval: str = "automatic"
    action_summary: str | None = None
    reply_on_success: bool = True


@dataclass
class ToolResult:
    """Outcome of running one ``ToolInvocation``."""

    func_name: str
    result: str
    status: str  # "success" | "error" | "unknown"
    original_tool_name: str | None = None
    target_edge: str | None = None

    @property
    def display_label(self) -> str:
        if self.original_tool_name and self.target_edge:
            return f"'{self.original_tool_name}' on '{self.target_edge}'"
        return f"'{self.func_name}'"
