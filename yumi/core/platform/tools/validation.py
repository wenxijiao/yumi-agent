"""Provider-facing tool-name validation.

OpenAI / Anthropic / Gemini all require a function name to match a tight charset
(letters, digits, underscore, hyphen) capped at 64 chars. One tool whose name
breaks that gets the WHOLE tools array rejected by the model API, so the server
validates names up front (after the edge prefix is applied) and drops offenders.
"""

from __future__ import annotations

import re

TOOL_NAME_PATTERN = r"^[a-zA-Z0-9_-]{1,64}$"
_TOOL_NAME_RE = re.compile(TOOL_NAME_PATTERN)


def is_valid_tool_name(name: object) -> bool:
    """True if *name* is a provider-safe function name."""
    return isinstance(name, str) and _TOOL_NAME_RE.match(name) is not None
