"""Normalises tool_calls emitted by a model and tracks format-retry budget.

The model occasionally emits malformed ``tool_calls`` (wrong shape, missing
JSON arguments). The orchestrator can ask the normalizer for one of three
outcomes per attempt:

* ``ready(tcalls)``    — usable invocations, proceed to dispatch.
* ``retry(message)``   — push a "regenerate" hint into the conversation and
                         go around again; emits a ``tool_status`` event.
* ``exhausted(diag)``  — too many failed attempts, emit error and break.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from kumi.core.dispatch.context import TurnContext
from kumi.core.tool_call_normalize import normalize_tool_calls, tool_call_format_retry_user_content


def summarize_tool_args(args: dict | None, max_len: int = 500) -> str:
    """Stable preview of tool arguments for logs and diagnostics."""
    if not args:
        return "{}"
    try:
        s = json.dumps(args, ensure_ascii=False)
    except Exception:
        s = str(args)
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s


@dataclass
class NormalizationOutcome:
    kind: str  # "ready" | "retry" | "exhausted"
    tcalls: list[dict] | None = None
    retry_attempt: int = 0
    raw_preview: str = ""


class ToolCallNormalizer:
    """Wraps ``normalize_tool_calls`` with retry-budget bookkeeping."""

    def __init__(self, *, max_retries: int) -> None:
        self.max_retries = max_retries

    def normalize(self, raw_tool_calls: list, ctx: TurnContext) -> NormalizationOutcome:
        tcalls = normalize_tool_calls(raw_tool_calls)
        if tcalls:
            ctx.tool_format_retries = 0
            return NormalizationOutcome(kind="ready", tcalls=tcalls)

        ctx.tool_format_retries += 1
        raw_preview = summarize_tool_args({"tool_calls": raw_tool_calls}, max_len=1000)
        ctx.tool_loop_events.append(
            {
                "loop": ctx.loop_count,
                "status": "error",
                "reason": "invalid_tool_call_format",
                "raw_preview": raw_preview,
            }
        )

        if ctx.tool_format_retries > self.max_retries:
            return NormalizationOutcome(kind="exhausted", raw_preview=raw_preview)

        ctx.ephemeral_messages.append(
            {
                "role": "user",
                "content": tool_call_format_retry_user_content(raw_tool_calls),
            }
        )
        return NormalizationOutcome(kind="retry", retry_attempt=ctx.tool_format_retries)
