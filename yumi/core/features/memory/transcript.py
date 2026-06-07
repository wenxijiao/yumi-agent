"""Transcript helpers for replay-safe chat history windows."""

from __future__ import annotations

import json

from yumi.core.features.memory.constants import YUMI_V1_TOOL_CALLS


def assistant_tool_call_count_from_stored_raw(raw: str) -> int | None:
    """Return the persisted assistant tool-call count, if *raw* stores one."""

    if not raw.startswith(YUMI_V1_TOOL_CALLS):
        return None
    try:
        data = json.loads(raw[len(YUMI_V1_TOOL_CALLS) :])
        tcalls = data.get("tool_calls")
        if isinstance(tcalls, list) and len(tcalls) > 0:
            return len(tcalls)
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def trim_trailing_incomplete_tool_rows(rows: list[dict]) -> list[dict]:
    """Drop a suffix that starts at an assistant tool-call row without enough tool rows."""

    if not rows:
        return rows
    out = list(rows)
    i = 0
    while i < len(out):
        if out[i].get("role") != "assistant":
            i += 1
            continue
        raw = out[i].get("content") or ""
        n = assistant_tool_call_count_from_stored_raw(raw)
        if not n:
            i += 1
            continue
        j = i + 1
        got = 0
        while j < len(out) and out[j].get("role") == "tool" and got < n:
            got += 1
            j += 1
        if got < n:
            return out[:i]
        i = j
    return out


def trim_leading_orphan_tool_rows(rows: list[dict]) -> list[dict]:
    """Drop tool rows whose preceding assistant tool-call turn was outside the window."""

    out = list(rows)
    while out and out[0].get("role") == "tool":
        out.pop(0)
    return out


def trim_leading_orphan_assistant_tool_calls(rows: list[dict]) -> list[dict]:
    """Drop a leading assistant tool-call (and its paired tool rows).

    A recent-transcript window can begin with an ``assistant`` row that is a
    pure tool-call when the user prompt that triggered it lives outside the
    window.  Strict providers (notably Gemini) reject such payloads with
    ``400 INVALID_ARGUMENT: function call turn comes immediately after a
    user turn or after a function response turn``.  Permissive providers
    (OpenAI, Claude, Ollama) accept it but the dangling call carries no
    semantic value once its prompt is gone.  Removing it is therefore safe
    and provider-agnostic.
    """

    out = list(rows)
    while out and out[0].get("role") == "assistant":
        raw = out[0].get("content") or ""
        n = assistant_tool_call_count_from_stored_raw(raw)
        if not n:
            break
        out.pop(0)
        while out and out[0].get("role") == "tool":
            out.pop(0)
    return out


def dedupe_consecutive_user_rows(rows: list[dict]) -> list[dict]:
    """Collapse runs of identical consecutive ``user`` rows into the latest copy.

    Identical user rows typically come from chat-client retries (Telegram bot
    reposts, web double-tap, network blips).  Forwarding all of them inflates
    prompts and frequently confuses tool-using models that interpret the
    repetition as new intent.  We keep the most recent occurrence so the
    visible timestamp stays current.
    """

    if not rows:
        return rows
    out: list[dict] = []
    for row in rows:
        if (
            row.get("role") == "user"
            and out
            and out[-1].get("role") == "user"
            and (out[-1].get("content") or "").strip() == (row.get("content") or "").strip()
            and (out[-1].get("content") or "").strip() != ""
        ):
            out[-1] = row
            continue
        out.append(row)
    return out
