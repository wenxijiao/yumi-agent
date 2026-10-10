"""Deterministic completion policy, selected by tool registration, never by the LLM."""

from __future__ import annotations

import json


def silent_success(invocations, results, *, requested_count: int) -> bool:
    # Do not swallow failed/denied calls, or results from other tools that the
    # user may still need explained. Process the entire approved batch first.
    if not invocations or len(invocations) != len(results) or len(invocations) != requested_count:
        return False
    for invocation, result in zip(invocations, results):
        if invocation.reply_on_success or result.status != "success":
            return False
        try:
            payload = json.loads(result.result)
        except (ValueError, TypeError):
            return False
        if not isinstance(payload, dict) or payload.get("ok") is not True or payload.get("error"):
            return False
    return True
