"""Pipeline limits shared by the chat-turn orchestrator and proactive runner."""

from __future__ import annotations

MAX_TOOL_LOOPS = 10
MAX_TOOL_CALL_FORMAT_RETRIES = 3
LOCAL_TOOL_TIMEOUT_DEFAULT = 30
TOOL_CALL_TIMEOUT_DEFAULT = 30

# Cap on tool-result text entering the model context (and, via persistence,
# the replayed transcript). An unbounded result would be re-billed on every
# subsequent request that replays it within the recent-message window.
TOOL_RESULT_MAX_CHARS = 8000
