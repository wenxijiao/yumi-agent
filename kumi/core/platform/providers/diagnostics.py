from __future__ import annotations

import json
import os
import re
import traceback
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from kumi.logging_config import get_logger

_logger = get_logger(__name__)
_DIAGNOSED_ATTR = "_kumi_provider_failure_diagnostic_path"


def debug_dir() -> str:
    """Return the directory used for provider failure diagnostics."""
    override = (os.getenv("KUMI_DEBUG_DIR") or "").strip()
    if override:
        return os.path.expanduser(override)
    return os.path.expanduser("~/.kumi/debug")


def short_text(value: Any, limit: int = 500) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:
            text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + f"...[truncated {len(text) - limit} chars]"


def summarize_openai_message(msg: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "role": msg.get("role"),
        "content_type": type(msg.get("content")).__name__,
        "content_preview": short_text(msg.get("content")),
    }
    if msg.get("name"):
        out["name"] = msg.get("name")
    tool_calls = msg.get("tool_calls")
    if isinstance(tool_calls, list):
        out["tool_calls"] = []
        for tc in tool_calls:
            fn = tc.get("function", {}) if isinstance(tc, dict) else {}
            out["tool_calls"].append(
                {
                    "id": tc.get("id") if isinstance(tc, dict) else None,
                    "name": fn.get("name"),
                    "arguments_preview": short_text(fn.get("arguments"), limit=300),
                    "has_thought_signature": bool(
                        isinstance(tc, dict) and (tc.get("thought_signature") or tc.get("thoughtSignature"))
                    ),
                }
            )
    return out


def summarize_tools(tools: list[dict] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tool in tools or []:
        fn = tool.get("function", {}) if isinstance(tool, dict) else {}
        params = fn.get("parameters", {}) if isinstance(fn, dict) else {}
        properties = params.get("properties", {}) if isinstance(params, dict) else {}
        out.append(
            {
                "name": fn.get("name"),
                "description_preview": short_text(fn.get("description"), limit=300),
                "parameter_names": list(properties.keys()) if isinstance(properties, dict) else [],
            }
        )
    return out


def provider_name(provider: Any) -> str:
    name = type(provider).__name__ if provider is not None else "unknown"
    if name.endswith("Provider"):
        name = name[: -len("Provider")]
    return name.lower() or "unknown"


def provider_failure_diagnostic_path(exc: Exception) -> str | None:
    value = getattr(exc, _DIAGNOSED_ATTR, None)
    return value if isinstance(value, str) and value else None


def _safe_filename_token(raw: str, *, max_len: int, fallback: str) -> str:
    """ASCII-ish token safe for filenames across macOS/Linux/Windows."""
    text = "".join(c if 32 <= ord(c) < 127 else " " for c in (raw or "").strip())
    text = re.sub(r"\s+", " ", text).strip()[: max_len * 2]
    token = re.sub(r"[^a-zA-Z0-9._-]+", "-", text)
    token = re.sub(r"-{2,}", "-", token).strip("-._")
    if not token:
        return fallback[:max_len]
    return token[:max_len]


def _diagnostic_error_hint(exc: Exception) -> str:
    """Short single-line hint from the exception for the filename."""
    msg = str(exc).strip()
    if not msg:
        return type(exc).__name__
    first = msg.split("\n", 1)[0].strip()
    for prefix in ("400 ", "401 ", "403 ", "404 ", "429 ", "500 ", "503 "):
        if first.startswith(prefix):
            first = first[len(prefix) :].lstrip()
            break
    if "{" in first and len(first) > 100:
        first = first.split("{", 1)[0].rstrip(": ").strip()
    return first or type(exc).__name__


def build_provider_diagnostic_filename(
    *,
    provider: str,
    phase: str,
    exc: Exception,
    model: str | None = None,
    note: str | None = None,
    now: datetime | None = None,
    unique_suffix_len: int = 8,
) -> str:
    """Build a self-describing diagnostic log basename (no directory, ends with ``.json``).

    Typical pattern:
    ``UTCstamp_provider_phase_model_error-hint_optional-note_rand.json``

    ``now`` is injectable for tests.
    """
    dt = now or datetime.now(timezone.utc)
    stamp = dt.strftime("%Y%m%dT%H%M%SZ")
    prov = _safe_filename_token(provider or "provider", max_len=24, fallback="provider")
    ph = _safe_filename_token(phase or "unknown", max_len=32, fallback="unknown")
    parts: list[str] = [stamp, prov, ph]
    model_tag = _safe_filename_token((model or "").strip(), max_len=40, fallback="")
    if model_tag:
        parts.append(model_tag)
    hint = _safe_filename_token(_diagnostic_error_hint(exc), max_len=56, fallback="error")
    parts.append(hint)
    if note and (n := _safe_filename_token(note, max_len=32, fallback="")):
        parts.append(n)
    body = "_".join(parts)
    unique = uuid4().hex[: max(4, min(16, unique_suffix_len))]
    return f"{body}_{unique}.json"


def write_provider_failure_diagnostic(
    *,
    exc: Exception,
    provider: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict] | None = None,
    session_id: str | None = None,
    prompt: str | None = None,
    phase: str = "chat_stream",
    extra: dict[str, Any] | None = None,
    filename_note: str | None = None,
) -> str | None:
    """Write a compact, redacted request snapshot for provider failures.

    ``filename_note`` is an optional short tag appended to the diagnostic filename
    (e.g. ``embed`` or ``retry``) for easier scanning in ``~/.kumi/debug/``.
    """
    existing = provider_failure_diagnostic_path(exc)
    if existing:
        return existing

    try:
        directory = debug_dir()
        os.makedirs(directory, exist_ok=True)
        basename = build_provider_diagnostic_filename(
            provider=provider,
            phase=phase,
            exc=exc,
            model=model,
            note=filename_note,
        )
        path = os.path.join(directory, basename)
        payload: dict[str, Any] = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "provider": provider,
            "model": model,
            "phase": phase,
            "session_id": session_id,
            "prompt_preview": short_text(prompt),
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
                "repr": repr(exc),
                "traceback": traceback.format_exception(type(exc), exc, exc.__traceback__),
            },
            "counts": {
                "messages": len(messages),
                "tools": len(tools or []),
            },
            "messages": [summarize_openai_message(m) for m in messages],
            "tools": summarize_tools(tools),
        }
        if extra:
            payload["extra"] = extra
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        try:
            setattr(exc, _DIAGNOSED_ATTR, path)
        except Exception:
            pass
        return path
    except Exception:
        _logger.debug("Failed to write provider request diagnostic", exc_info=True)
        return None


def write_chat_loop_diagnostic(
    *,
    session_id: str,
    prompt: str | None,
    model: str | None,
    loop_count: int,
    messages: list[dict[str, Any]],
    tools: list[dict] | None,
    extra: dict[str, Any] | None = None,
) -> str | None:
    """Write a debug snapshot when chat tool execution loops are stopped."""
    return write_chat_diagnostic(
        phase="chat_tool_loop",
        session_id=session_id,
        prompt=prompt,
        model=model,
        messages=messages,
        tools=tools,
        extra={"loop_count": loop_count, **(extra or {})},
    )


def write_chat_diagnostic(
    *,
    phase: str,
    session_id: str,
    prompt: str | None,
    model: str | None,
    messages: list[dict[str, Any]],
    tools: list[dict] | None,
    error: BaseException | None = None,
    extra: dict[str, Any] | None = None,
) -> str | None:
    """Write a debug snapshot for non-provider chat pipeline failures."""
    try:
        directory = debug_dir()
        os.makedirs(directory, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        model_tag = _safe_filename_token(model or "unknown-model", max_len=40, fallback="model")
        session_tag = _safe_filename_token(session_id or "session", max_len=32, fallback="session")
        phase_tag = _safe_filename_token(phase or "chat", max_len=32, fallback="chat")
        unique = uuid4().hex[:8]
        path = os.path.join(directory, f"{stamp}_{phase_tag}_{model_tag}_{session_tag}_{unique}.json")
        payload: dict[str, Any] = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "phase": phase,
            "session_id": session_id,
            "model": model,
            "prompt_preview": short_text(prompt, limit=2000),
            "counts": {
                "messages": len(messages),
                "tools": len(tools or []),
            },
            "messages": [summarize_openai_message(m) for m in messages],
            "tools": summarize_tools(tools),
        }
        if error is not None:
            payload["error"] = {
                "type": type(error).__name__,
                "message": str(error),
                "repr": repr(error),
                "traceback": traceback.format_exception(type(error), error, error.__traceback__),
            }
        if extra and "loop_count" in extra:
            payload["loop_count"] = extra["loop_count"]
        if extra:
            payload["extra"] = extra
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        return path
    except Exception:
        _logger.debug("Failed to write chat diagnostic", exc_info=True)
        return None
