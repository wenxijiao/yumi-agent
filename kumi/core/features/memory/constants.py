"""Shared constants for LanceDB message layout and session metadata."""

# Stored assistant rows that only carry tool_calls (OpenAI-style), for replay in get_context.
KUMI_V1_TOOL_CALLS = "__kumi:v1:tc__\n"
# Stored tool result rows (name + content JSON), role=tool in DB.
KUMI_V1_TOOL_RESULT = "__kumi:v1:tool__\n"

DEFAULT_SESSION_TITLE = "New chat"
ACTIVE_SESSION_STATUS = "active"
DELETED_SESSION_STATUS = "deleted"
