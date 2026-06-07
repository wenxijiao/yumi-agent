"""Convert provider-native tool call objects into plain OpenAI-style dicts.

Ollama (and some OpenAI SDK paths) may emit Pydantic ``ToolCall`` instances.
Those must not reach ``json.dumps`` (memory persistence) or providers that
expect JSON-serializable message payloads.
"""

from __future__ import annotations

import json
from typing import Any

from json_repair import repair_json


def normalize_tool_calls(tcalls: Any) -> list[dict[str, Any]]:
    """Return a list of ``{"id", "type", "function": {"name", "arguments"}}`` dicts.

    * *arguments* is always a ``dict`` (empty if missing or invalid).
    * Unknown / empty items are skipped.
    """
    if tcalls is None:
        return []
    if isinstance(tcalls, dict):
        items: list[Any] = [tcalls]
    elif isinstance(tcalls, (list, tuple)):
        items = list(tcalls)
    else:
        # Single SDK object (e.g. one ``ToolCall``) from a provider
        items = [tcalls]

    out: list[dict[str, Any]] = []
    for tc in items:
        one = _single_tool_call_to_dict(tc)
        if one is not None:
            out.append(one)
    return out


def _coerce_arguments(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return {}
        try:
            parsed = json.loads(s)
        except (json.JSONDecodeError, TypeError):
            try:
                parsed = repair_json(s, return_objects=True)
            except Exception:
                return {}
        return parsed if isinstance(parsed, dict) else {"_value": parsed}
    if hasattr(raw, "model_dump") and callable(raw.model_dump):
        try:
            dumped = raw.model_dump(mode="json")
        except TypeError:
            dumped = raw.model_dump()
        if isinstance(dumped, dict):
            return dumped
        return {}
    return {}


def _single_tool_call_to_dict(tc: Any) -> dict[str, Any] | None:
    if tc is None:
        return None

    if isinstance(tc, dict):
        fn = tc.get("function")
        if not isinstance(fn, dict):
            return None
        name = fn.get("name") or ""
        if not str(name).strip():
            return None
        args = _coerce_arguments(fn.get("arguments"))
        out = {
            "id": str(tc.get("id") or ""),
            "type": str(tc.get("type") or "function"),
            "function": {"name": str(name), "arguments": args},
        }
        thought_signature = tc.get("thought_signature") or tc.get("thoughtSignature")
        if isinstance(thought_signature, str) and thought_signature.strip():
            # Gemini 3 requires replayed functionCall parts to carry this
            # opaque token. Keep it JSON-safe while still returning the
            # provider-neutral OpenAI-style tool call shape.
            out["thought_signature"] = thought_signature.strip()
        return out

    if hasattr(tc, "model_dump") and callable(tc.model_dump):
        try:
            data = tc.model_dump(mode="json")
        except TypeError:
            data = tc.model_dump()
        if isinstance(data, dict) and isinstance(data.get("function"), dict):
            return _single_tool_call_to_dict(data)
        return None

    fn_obj = getattr(tc, "function", None)
    if fn_obj is None:
        return None
    name = getattr(fn_obj, "name", None) or ""
    if not str(name).strip():
        return None
    args = _coerce_arguments(getattr(fn_obj, "arguments", None))
    oid = getattr(tc, "id", None)
    typ = getattr(tc, "type", None) or "function"
    return {
        "id": str(oid) if oid is not None else "",
        "type": str(typ),
        "function": {"name": str(name), "arguments": args},
    }


def tool_calls_payload_preview(raw: Any, max_len: int = 700) -> str:
    """Best-effort string for logging / model feedback (always JSON-safe text)."""
    try:
        s = json.dumps(raw, ensure_ascii=False, default=str)
    except TypeError:
        s = repr(raw)
    if len(s) > max_len:
        return s[: max_len - 3] + "..."
    return s


def explain_tool_calls_normalize_failure(raw: Any) -> str:
    """Short English diagnosis when :func:`normalize_tool_calls` returns ``[]``."""
    if raw is None:
        return "The tool_calls value was None."
    if isinstance(raw, dict):
        items: list[Any] = [raw]
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        items = [raw]
    if not items:
        return "The tool_calls list was empty."
    parts: list[str] = []
    for i, item in enumerate(items[:6]):
        if item is None:
            parts.append(f"Item {i} is None.")
            continue
        if isinstance(item, dict):
            fn = item.get("function")
            if not isinstance(fn, dict):
                parts.append(f"Item {i} has no object-shaped `function` field (got {type(fn).__name__}).")
                continue
            name = fn.get("name")
            if not (name and str(name).strip()):
                parts.append(f"Item {i} has an empty or missing function.name.")
            args = fn.get("arguments", None)
            if args is not None and not isinstance(args, (dict, str)) and not hasattr(args, "model_dump"):
                parts.append(f"Item {i} has unsupported function.arguments type {type(args).__name__}.")
        elif hasattr(item, "function"):
            name = getattr(getattr(item, "function", None), "name", None) or ""
            if not str(name).strip():
                parts.append(f"Item {i} is an object tool call with an empty function.name.")
        else:
            parts.append(f"Item {i} has type {type(item).__name__} and is not a recognized tool call shape.")
    if len(items) > 6:
        parts.append(f"...and {len(items) - 6} more item(s) were not shown.")
    return " ".join(parts) if parts else "No item could be converted to an executable tool call."


def tool_call_format_retry_user_content(raw: Any) -> str:
    """Ephemeral ``user`` message instructing the model to regenerate tool calls."""
    explain = explain_tool_calls_normalize_failure(raw)
    preview = tool_calls_payload_preview(raw)
    return (
        "[Yumi · tool call format]\n\n"
        "Your previous assistant turn included `tool_calls` that this server could not parse into "
        "executable tool invocations.\n\n"
        f"Diagnosis: {explain}\n\n"
        f"Raw payload (truncated): {preview}\n\n"
        "Required shape (OpenAI-compatible): each entry must have `function.name` as a non-empty string, "
        "and `function.arguments` as a JSON object describing parameters (or a JSON string that parses "
        "to an object).\n\n"
        "Please send your next message again: issue valid tool calls, or answer without tools if that "
        "is more appropriate."
    )
