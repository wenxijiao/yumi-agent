"""Per-session chat debug tracing: NDJSON log under ``debug_dir()/chat_trace/``."""

from __future__ import annotations

import copy
import json
import os
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from kumi.core.providers.diagnostics import debug_dir
from kumi.logging_config import get_logger

_logger = get_logger(__name__)

# Qualified session_id -> absolute path of active .ndjson trace file.
_TRACES: dict[str, str] = {}


def chat_debug_redact_image_data_urls() -> bool:
    """If true, replace ``data:image/...;base64,...`` URLs in logged messages with a short placeholder (smaller traces)."""
    raw = (os.getenv("KUMI_CHAT_DEBUG_REDACT_IMAGE_DATA") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _redact_data_urls_in_value(value: Any) -> Any:
    if isinstance(value, str) and value.startswith("data:") and ";base64," in value:
        return f"{value.split(',', 1)[0]},...[base64 redacted {len(value)} chars total]"
    if isinstance(value, list):
        return [_redact_data_urls_in_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _redact_data_urls_in_value(v) for k, v in value.items()}
    return value


def _safe_dir_name(session_id: str, max_len: int = 80) -> str:
    text = "".join(c if 32 <= ord(c) < 127 else "_" for c in (session_id or "").strip())
    text = re.sub(r"\s+", "_", text).strip()[: max_len * 2]
    token = re.sub(r"[^a-zA-Z0-9._-]+", "-", text)
    token = re.sub(r"-{2,}", "-", token).strip("-._")
    return token[:max_len] if token else "session"


def _utc_ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_tracing(qualified_session_id: str) -> bool:
    return qualified_session_id in _TRACES


def get_trace_path(qualified_session_id: str) -> str | None:
    return _TRACES.get(qualified_session_id)


def append_record(qualified_session_id: str, record: dict) -> None:
    path = _TRACES.get(qualified_session_id)
    if not path:
        return
    try:
        row = dict(record)
        if "ts" not in row:
            row["ts"] = _utc_ts()
        line = json.dumps(row, ensure_ascii=False, default=str) + "\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
    except Exception:
        _logger.debug("chat debug trace append failed", exc_info=True)


def append_stream_event(qualified_session_id: str, event: dict) -> None:
    append_record(qualified_session_id, {"kind": "stream_event", "event": dict(event)})


def append_turn_begin(
    qualified_session_id: str,
    *,
    prompt: str,
    think: bool,
    timer_callback: bool,
) -> None:
    append_record(
        qualified_session_id,
        {
            "kind": "turn_begin",
            "session_id": qualified_session_id,
            "prompt": prompt,
            "think": think,
            "timer_callback": timer_callback,
        },
    )


def append_turn_end(
    qualified_session_id: str,
    *,
    model: str | None,
    total_prompt_tokens: int,
    total_completion_tokens: int,
    usage_model: str,
) -> None:
    append_record(
        qualified_session_id,
        {
            "kind": "turn_end",
            "model": model,
            "total_prompt_tokens": total_prompt_tokens,
            "total_completion_tokens": total_completion_tokens,
            "usage_model": usage_model,
        },
    )


def append_llm_provider_request(
    qualified_session_id: str,
    *,
    model: str,
    messages: list[dict],
    tools: list[dict] | None,
    note: str | None = None,
) -> None:
    """Log the exact *messages* and *tools* passed to the LLM provider (after ``compose_messages``).

    Includes system prompts, session/memory context, tool results, and multimodal parts.
    Set ``KUMI_CHAT_DEBUG_REDACT_IMAGE_DATA=1`` to shorten inline ``data:`` image URLs in the log only.
    """
    try:
        msgs = copy.deepcopy(messages)
    except Exception:
        msgs = [dict(m) for m in messages]
    try:
        tls = copy.deepcopy(tools) if tools is not None else None
    except Exception:
        tls = tools
    if chat_debug_redact_image_data_urls():
        msgs = _redact_data_urls_in_value(msgs)  # type: ignore[assignment]
        tls = _redact_data_urls_in_value(tls) if tls is not None else None
    rec: dict[str, Any] = {
        "kind": "llm_provider_request",
        "model": model,
        "messages": msgs,
        "tools": tls,
    }
    if note:
        rec["note"] = note
    append_record(qualified_session_id, rec)


def start_trace(qualified_session_id: str) -> str:
    """Begin trace for *qualified_session_id*; returns trace file path (existing if already tracing)."""
    existing = _TRACES.get(qualified_session_id)
    if existing:
        return existing
    base = os.path.join(debug_dir(), "chat_trace", _safe_dir_name(qualified_session_id))
    os.makedirs(base, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(base, f"{stamp}_{uuid4().hex[:8]}.ndjson")
    _TRACES[qualified_session_id] = path
    append_record(
        qualified_session_id,
        {
            "kind": "meta",
            "action": "start",
            "session_id": qualified_session_id,
            "trace_path": path,
        },
    )
    return path


def stop_trace(qualified_session_id: str) -> str | None:
    """Stop trace; writes meta end and returns path, or None if not tracing."""
    path = _TRACES.get(qualified_session_id)
    if not path:
        return None
    try:
        append_record(
            qualified_session_id,
            {
                "kind": "meta",
                "action": "end",
                "session_id": qualified_session_id,
                "trace_path": path,
            },
        )
    finally:
        _TRACES.pop(qualified_session_id, None)
    return path
