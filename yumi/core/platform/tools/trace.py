"""In-memory tool call traces with optional JSONL persistence (~/.yumi/tool_traces.jsonl)."""

from __future__ import annotations

import json
import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_BUFFER = 2000
MAX_ARG_CHARS = 4096
MAX_RESULT_CHARS = 2000
_MAX_FILE_TAIL_LINES = 800
_MAX_REDACT_DEPTH = 12
_SENSITIVE_KEY_NAMES = {
    "api_key",
    "apikey",
    "api-key",
    "access_key",
    "access-key",
    "key",
    "password",
    "passwd",
    "pwd",
    "authorization",
    "auth",
    "cookie",
}
_SENSITIVE_KEY_FRAGMENTS = (
    "api_key",
    "access_token",
    "refresh_token",
    "id_token",
    "auth_token",
    "bearer_token",
    "secret",
    "password",
    "private_key",
    "credential",
)

_buffer: deque[dict[str, Any]] = deque(maxlen=MAX_BUFFER)
_lock = threading.Lock()
_disk_bootstrapped = False


def _trace_file() -> Path:
    return Path.home() / ".yumi" / "tool_traces.jsonl"


def _is_sensitive_key(key: Any) -> bool:
    normalized = str(key).strip().lower().replace("-", "_").replace(" ", "_")
    return normalized in _SENSITIVE_KEY_NAMES or any(fragment in normalized for fragment in _SENSITIVE_KEY_FRAGMENTS)


def _redact_sensitive(value: Any, *, depth: int = 0) -> Any:
    if depth > _MAX_REDACT_DEPTH:
        return "[truncated]"
    if isinstance(value, dict):
        return {
            str(key): "[redacted]" if _is_sensitive_key(key) else _redact_sensitive(val, depth=depth + 1)
            for key, val in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact_sensitive(item, depth=depth + 1) for item in value]
    return value


def _truncate_args(args: Any) -> Any:
    """Limit size of stored arguments for logs (privacy + storage)."""
    args = _redact_sensitive(args)
    try:
        s = json.dumps(args, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        s = str(args)
    if len(s) > MAX_ARG_CHARS:
        return s[: MAX_ARG_CHARS - 3] + "..."
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return s


def _truncate_result_preview(result_preview: str | None) -> str:
    if not result_preview:
        return ""
    text = str(result_preview)
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return text[:MAX_RESULT_CHARS]
    try:
        text = json.dumps(_redact_sensitive(parsed), ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(parsed)
    return text[:MAX_RESULT_CHARS]


def _bootstrap_from_disk_if_needed() -> None:
    global _disk_bootstrapped
    if _disk_bootstrapped:
        return
    _disk_bootstrapped = True
    path = _trace_file()
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    tail = lines[-_MAX_FILE_TAIL_LINES:]
    with _lock:
        for line in tail:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict) and rec.get("id"):
                _buffer.appendleft(rec)


def record_tool_trace(
    *,
    session_id: str,
    tool_name: str,
    kind: str,
    edge_name: str | None,
    display_name: str,
    arguments: Any,
    status: str,
    duration_ms: int,
    result_preview: str | None = None,
) -> None:
    """Append one completed tool invocation (success, error, or denied)."""
    _bootstrap_from_disk_if_needed()
    rec = {
        "id": str(uuid.uuid4()),
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "tool_name": tool_name,
        "display_name": display_name,
        "kind": kind,
        "edge_name": edge_name,
        "arguments": _truncate_args(arguments),
        "status": status,
        "duration_ms": duration_ms,
        "result_preview": _truncate_result_preview(result_preview),
    }
    with _lock:
        _buffer.appendleft(rec)
    _append_jsonl_line(rec)


def _append_jsonl_line(rec: dict[str, Any]) -> None:
    path = _trace_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def list_traces(
    *,
    session_id: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return newest-first traces, optionally filtered by session_id."""
    _bootstrap_from_disk_if_needed()
    limit = max(1, min(500, limit))
    with _lock:
        items = list(_buffer)
    out: list[dict[str, Any]] = []
    for rec in items:
        if session_id and rec.get("session_id") != session_id:
            continue
        out.append(dict(rec))
        if len(out) >= limit:
            break
    return out


def snapshot_traces(*, session_id: str | None = None) -> list[dict[str, Any]]:
    """All buffered traces (newest-first), unclamped — for in-process aggregation/export.

    ``list_traces`` caps at 500 for API responses; this returns the full ring
    buffer (up to ``MAX_BUFFER``) so stats and exports are not silently truncated.
    """
    _bootstrap_from_disk_if_needed()
    with _lock:
        items = list(_buffer)
    if session_id:
        return [dict(r) for r in items if r.get("session_id") == session_id]
    return [dict(r) for r in items]


def export_traces_json_lines(session_id: str | None = None) -> str:
    """All matching traces as NDJSON (oldest first in file order for export readability)."""
    rows = snapshot_traces(session_id=session_id)
    return "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in reversed(rows)) + "\n"


def clear_memory_buffer() -> None:
    """Clear in-memory ring buffer (does not delete JSONL file)."""
    with _lock:
        _buffer.clear()
