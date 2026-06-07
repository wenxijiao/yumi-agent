"""In-memory tool call traces with optional JSONL persistence (~/.kumi/tool_traces.jsonl)."""

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
_MAX_FILE_TAIL_LINES = 800

_buffer: deque[dict[str, Any]] = deque(maxlen=MAX_BUFFER)
_lock = threading.Lock()
_disk_bootstrapped = False


def _trace_file() -> Path:
    return Path.home() / ".kumi" / "tool_traces.jsonl"


def _truncate_args(args: Any) -> Any:
    """Limit size of stored arguments for logs (privacy + storage)."""
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
        "result_preview": (result_preview or "")[:2000],
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


def export_traces_json_lines(session_id: str | None = None) -> str:
    """All matching traces as NDJSON (oldest first in file order for export readability)."""
    rows = list_traces(session_id=session_id, limit=MAX_BUFFER)
    return "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in reversed(rows)) + "\n"


def clear_memory_buffer() -> None:
    """Clear in-memory ring buffer (does not delete JSONL file)."""
    with _lock:
        _buffer.clear()
