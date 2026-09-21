"""Live chat-turn records shared by the chat UI and Debug inspector.

The in-memory ring holds running/recent turns so the UI can update live.  At
turn completion the chat feature writes the returned public snapshot to the
owner's canonical SQLite store, where it remains part of conversation history.
"""

from __future__ import annotations

import copy
import json
import math
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

MAX_TURNS = 24
TURN_TRACE_SCHEMA_VERSION = 1

_lock = threading.RLock()
_turns: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
_active_by_session: dict[str, str] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short(value: Any, limit: int | None = None) -> Any:  # noqa: ARG001
    """Return a complete JSON-safe copy suitable for persistence and display."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return {str(k): _short(v, limit) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_short(v, limit) for v in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _short(str(value), limit)


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, ensure_ascii=False, default=str)
    except Exception:
        return str(content)


def _approx_tokens(value: Any) -> int:
    """Cheap display-only estimate; provider usage remains the authoritative total."""
    chars = len(_content_text(value))
    return 0 if chars == 0 else max(1, math.ceil(chars / 4))


def _message_label(message: dict[str, Any], index: int, total: int, current_prompt: str) -> str:
    role = str(message.get("role") or "unknown")
    content = _content_text(message.get("content"))
    if role == "tool":
        return "Tool result"
    if role == "assistant":
        return "Assistant tool call" if message.get("tool_calls") else "Assistant history"
    if role == "user":
        same_as_current = bool(current_prompt) and content.strip() == current_prompt.strip()
        return "Current user message" if same_as_current or index == total - 1 else "Conversation history"
    if role != "system":
        return role.title()
    if index == 0:
        return "Base system prompt"
    if content.startswith("Stable User Context:"):
        return "Stable user context"
    if content.startswith("Summary of the earlier part"):
        return "Session summary"
    if content.startswith("Structured memory likely relevant"):
        return "Relevant structured memory"
    if content.startswith("Relevant memory from previous chats"):
        return "Related cross-session memory"
    if content.startswith("[Turn Runtime Context]"):
        return "Turn runtime context"
    if content.startswith("[Turn language]"):
        return "Turn language"
    if content.startswith("[Current Time]"):
        return "Current time"
    if content.startswith("[Server file paths") or content.startswith("[Uploaded images"):
        return "Upload guidance"
    return "System note"


def _display_messages(messages: list[dict], current_prompt: str) -> list[dict[str, Any]]:
    safe = _short(messages)
    rows: list[dict[str, Any]] = []
    total = len(safe)
    for index, raw in enumerate(safe):
        msg = raw if isinstance(raw, dict) else {"content": raw}
        content = msg.get("content")
        row: dict[str, Any] = {
            "index": index,
            "role": str(msg.get("role") or "unknown"),
            "label": _message_label(msg, index, total, current_prompt),
            "content": content,
            "content_chars": len(_content_text(content)),
            "approx_tokens": _approx_tokens(content),
        }
        for key in ("name", "tool_call_id", "tool_calls", "reasoning_content"):
            if key in msg:
                row[key] = msg[key]
        rows.append(row)
    return rows


def _tool_name(tool: Any) -> str:
    if not isinstance(tool, dict):
        return "unknown"
    fn = tool.get("function")
    if isinstance(fn, dict) and fn.get("name"):
        return str(fn["name"])
    return str(tool.get("name") or tool.get("server_label") or tool.get("type") or "unknown")


def _active_turn(session_id: str) -> dict[str, Any] | None:
    turn_id = _active_by_session.get(session_id)
    return _turns.get(turn_id) if turn_id else None


def _latest_round(turn: dict[str, Any]) -> dict[str, Any] | None:
    rounds = turn.get("rounds") or []
    return rounds[-1] if rounds else None


def _event(turn: dict[str, Any], kind: str, label: str, **extra: Any) -> None:
    turn.setdefault("timeline", []).append(
        {
            "ts": _now(),
            "kind": kind,
            "label": label,
            **_short(extra),
        }
    )


def begin_turn(
    *,
    turn_id: str,
    session_id: str,
    prompt: str,
    think: bool,
    timer_callback: bool,
    prompt_metadata: dict[str, str] | None = None,
    owner_user_id: str = "",
    started_monotonic: float | None = None,
    started_at: str | None = None,
) -> None:
    with _lock:
        previous = _active_turn(session_id)
        if previous is not None and previous.get("status") == "running":
            previous["status"] = "interrupted"
            previous["ended_at"] = _now()
            previous["duration_ms"] = int((time.perf_counter() - previous.pop("_started", time.perf_counter())) * 1000)

        turn: dict[str, Any] = {
            "trace_schema_version": TURN_TRACE_SCHEMA_VERSION,
            "id": turn_id,
            "session_id": session_id,
            "owner_user_id": owner_user_id,
            "prompt": _short(prompt),
            "prompt_preview": " ".join((prompt or "").split())[:180],
            "think": bool(think),
            "timer_callback": bool(timer_callback),
            "started_at": started_at or _now(),
            "ended_at": None,
            "duration_ms": None,
            "status": "running",
            "routing": {},
            "rounds": [],
            "timeline": [],
            **(prompt_metadata or {}),
            "_started": time.perf_counter() if started_monotonic is None else started_monotonic,
        }
        _turns[turn_id] = turn
        _turns.move_to_end(turn_id)
        _active_by_session[session_id] = turn_id
        _event(turn, "turn", "Turn started")

        while len(_turns) > MAX_TURNS:
            oldest_id, oldest = next(
                ((key, value) for key, value in _turns.items() if value.get("status") != "running"),
                next(iter(_turns.items())),
            )
            _turns.pop(oldest_id, None)
            if _active_by_session.get(str(oldest.get("session_id") or "")) == oldest_id:
                _active_by_session.pop(str(oldest.get("session_id") or ""), None)


def record_routing(session_id: str, routing: dict[str, Any]) -> None:
    with _lock:
        turn = _active_turn(session_id)
        if turn is None:
            return
        turn["routing"] = _short(routing)
        selected = int(routing.get("selected_edge_count") or 0)
        total = int(routing.get("total_edge_count") or 0)
        core = int(routing.get("core_count") or 0)
        _event(
            turn,
            "routing",
            f"Selected {core + selected} tool(s)",
            detail=f"{core} core · {selected}/{total} edge",
            duration_ms=routing.get("elapsed_ms"),
        )


def record_llm_request(
    session_id: str,
    *,
    provider: str,
    model: str,
    messages: list[dict],
    tools: list[dict] | None,
    note: str | None = None,
) -> None:
    with _lock:
        turn = _active_turn(session_id)
        if turn is None:
            return
        previous_round = _latest_round(turn)
        if previous_round is not None and not previous_round.get("ended_at"):
            previous_round["finish"] = {
                "reason": "retry",
                "provider_reason": note or "new_provider_request",
            }
            _close_round(turn, previous_round)
        safe_tools = _short(tools or [])
        index = len(turn["rounds"]) + 1
        from yumi.core.platform.providers.budget import token_estimate

        round_record: dict[str, Any] = {
            "index": index,
            "started_at": _now(),
            "ended_at": None,
            "duration_ms": None,
            "provider": provider or "unknown",
            "model": model,
            "messages": _display_messages(messages, str(turn.get("prompt") or "")),
            "input_estimate": {
                "messages": token_estimate(messages),
                "tools": token_estimate(tools or []),
                "by_message": [{"role": m.get("role"), "tokens": token_estimate(m)} for m in messages],
            },
            "tools": safe_tools,
            "tool_names": [_tool_name(tool) for tool in safe_tools],
            "usage": {},
            "finish": None,
            "tool_calls": [],
            "tool_results": [],
            "response_text": "",
            "reasoning_text": "",
            "note": note,
            "_started": time.perf_counter(),
        }
        turn["rounds"].append(round_record)
        _event(
            turn,
            "llm_request",
            f"LLM round {index} started",
            round=index,
            detail=f"{provider} · {model} · {len(messages)} messages · {len(safe_tools)} tools",
        )


def record_model_settings(session_id: str, settings: dict[str, Any]) -> None:
    """Record what the adapter requested, separately from observed reasoning."""
    with _lock:
        turn = _active_turn(session_id)
        if turn is None:
            return
        current = _latest_round(turn)
        if current is not None:
            current["model_settings"] = {k: v for k, v in settings.items() if k != "type"}


def record_usage(session_id: str, usage: dict[str, Any]) -> None:
    with _lock:
        turn = _active_turn(session_id)
        round_record = _latest_round(turn) if turn is not None else None
        if round_record is None:
            return
        current = round_record.setdefault("usage", {})
        for key, value in usage.items():
            if key == "type":
                continue
            if key.endswith("tokens"):
                current[key] = int(current.get(key, 0) or 0) + int(value or 0)
            else:
                current[key] = _short(value)
        _event(
            turn,
            "usage",
            f"LLM round {round_record['index']} usage received",
            round=round_record["index"],
            prompt_tokens=current.get("prompt_tokens", 0),
            completion_tokens=current.get("completion_tokens", 0),
            cached_prompt_tokens=current.get("cached_prompt_tokens", 0),
        )


def _close_round(turn: dict[str, Any], round_record: dict[str, Any]) -> None:
    if round_record.get("ended_at"):
        return
    round_record["ended_at"] = _now()
    started = round_record.pop("_started", None)
    if isinstance(started, (int, float)):
        round_record["duration_ms"] = int((time.perf_counter() - started) * 1000)


def record_finish(session_id: str, finish: dict[str, Any]) -> None:
    with _lock:
        turn = _active_turn(session_id)
        round_record = _latest_round(turn) if turn is not None else None
        if round_record is None:
            return
        round_record["finish"] = _short({k: v for k, v in finish.items() if k != "type"})
        _close_round(turn, round_record)
        _event(
            turn,
            "llm_finish",
            f"LLM round {round_record['index']} finished",
            round=round_record["index"],
            status=round_record["finish"].get("reason"),
            detail=round_record["finish"].get("provider_reason"),
            duration_ms=round_record.get("duration_ms"),
        )


def record_tool_calls(session_id: str, *, loop: int, tool_calls: list[dict]) -> None:
    with _lock:
        turn = _active_turn(session_id)
        round_record = _latest_round(turn) if turn is not None else None
        if round_record is None:
            return
        safe_calls = _short(tool_calls)
        round_record["tool_calls"] = safe_calls
        if round_record.get("finish") is None:
            round_record["finish"] = {"reason": "tool_calls", "provider_reason": None}
        _close_round(turn, round_record)
        names = []
        for call in safe_calls:
            fn = call.get("function", {}) if isinstance(call, dict) else {}
            names.append(str(fn.get("name") or "unknown"))
        _event(
            turn,
            "tool_calls",
            f"LLM requested {len(safe_calls)} tool(s)",
            round=round_record["index"],
            loop=loop,
            tools=names,
            detail=", ".join(names),
        )


def record_tool_result(
    session_id: str,
    *,
    loop: int,
    call_id: str,
    tool: str,
    resolved_tool: str,
    kind: str,
    edge: str | None,
    status: str,
    duration_ms: int | None,
    result_preview: Any,
) -> None:
    with _lock:
        turn = _active_turn(session_id)
        round_record = _latest_round(turn) if turn is not None else None
        if turn is None or round_record is None:
            return
        row = {
            "loop": loop,
            "call_id": call_id,
            "tool": tool,
            "resolved_tool": resolved_tool,
            "kind": kind,
            "edge": edge,
            "status": status,
            "duration_ms": duration_ms,
            "result_preview": _short(result_preview),
        }
        round_record.setdefault("tool_results", []).append(row)
        _event(
            turn,
            "tool_result",
            f"{tool} {status}",
            round=round_record["index"],
            loop=loop,
            tool=tool,
            status=status,
            duration_ms=duration_ms,
            detail=(f"{kind} · {edge}" if edge else kind),
        )


def record_stream_event(session_id: str, event: dict[str, Any]) -> None:
    with _lock:
        turn = _active_turn(session_id)
        if turn is None:
            return
        round_record = _latest_round(turn)
        event_type = str(event.get("type") or "")
        content = str(event.get("content") or "")
        if round_record is not None and event_type in {"text", "thought"}:
            if content and "first_response_ms" not in turn:
                turn["first_response_ms"] = int(
                    (time.perf_counter() - turn.get("_started", time.perf_counter())) * 1000
                )
            key = "response_text" if event_type == "text" else "reasoning_text"
            existing = str(round_record.get(key) or "")
            round_record[key] = existing + content
            return
        if event_type == "tool_status":
            _event(
                turn,
                "tool_status",
                content or "Tool status",
                round=round_record.get("index") if round_record else None,
                status=event.get("status"),
            )
        elif event_type == "tool_confirmation":
            _event(
                turn,
                "confirmation",
                f"Confirmation requested for {event.get('tool_name') or 'tool'}",
                round=round_record.get("index") if round_record else None,
                tool=event.get("tool_name"),
                status="waiting",
            )
        elif event_type == "error":
            turn["status"] = "error"
            _event(
                turn,
                "error",
                content or "Turn failed",
                round=round_record.get("index") if round_record else None,
                status=event.get("code") or "error",
            )


def record_confirmation_wait(session_id: str, duration_ms: int) -> None:
    with _lock:
        turn = _active_turn(session_id)
        if turn is not None:
            turn["confirmation_wait_ms"] = turn.get("confirmation_wait_ms", 0) + max(0, duration_ms)


def end_turn(
    session_id: str,
    *,
    total_prompt_tokens: int,
    total_completion_tokens: int,
    usage_model: str,
    tool_loop_events: list[dict] | None = None,
) -> dict[str, Any] | None:
    with _lock:
        turn = _active_turn(session_id)
        if turn is None:
            return None
        round_record = _latest_round(turn)
        if round_record is not None:
            _close_round(turn, round_record)
        turn["ended_at"] = _now()
        started = turn.pop("_started", None)
        if isinstance(started, (int, float)):
            turn["duration_ms"] = int((time.perf_counter() - started) * 1000)
        if turn.get("status") == "running":
            turn["status"] = "complete"
        turn.setdefault("confirmation_wait_ms", 0)
        turn["usage"] = {
            "prompt_tokens": int(total_prompt_tokens or 0),
            "completion_tokens": int(total_completion_tokens or 0),
            "total_tokens": int(total_prompt_tokens or 0) + int(total_completion_tokens or 0),
            "model": usage_model or (round_record or {}).get("model") or "",
            "cached_prompt_tokens": sum(
                int((r.get("usage") or {}).get("cached_prompt_tokens", 0) or 0) for r in turn.get("rounds", [])
            ),
            "cache_write_prompt_tokens": sum(
                int((r.get("usage") or {}).get("cache_write_prompt_tokens", 0) or 0) for r in turn.get("rounds", [])
            ),
        }
        if tool_loop_events:
            turn["tool_loop_events"] = _short(tool_loop_events)
        _event(
            turn,
            "turn",
            "Turn completed" if turn["status"] == "complete" else "Turn ended with an error",
            status=turn["status"],
            duration_ms=turn.get("duration_ms"),
        )
        if _active_by_session.get(session_id) == turn.get("id"):
            _active_by_session.pop(session_id, None)
        public = copy.deepcopy(turn)
        public.pop("_started", None)
        for item in public.get("rounds") or []:
            item.pop("_started", None)
        public["summary"] = _summary(public)
        return public


def _summary(turn: dict[str, Any]) -> dict[str, Any]:
    rounds = turn.get("rounds") or []
    usage = turn.get("usage") or {}
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    cached = int(usage.get("cached_prompt_tokens") or 0)
    last = rounds[-1] if rounds else {}
    tool_call_count = sum(len(r.get("tool_calls") or []) for r in rounds)
    response = str(last.get("response_text") or "")
    return {
        "trace_schema_version": turn.get("trace_schema_version", TURN_TRACE_SCHEMA_VERSION),
        "id": turn.get("id"),
        "session_id": turn.get("session_id"),
        "owner_user_id": turn.get("owner_user_id"),
        "prompt_preview": turn.get("prompt_preview"),
        "started_at": turn.get("started_at"),
        "ended_at": turn.get("ended_at"),
        "duration_ms": turn.get("duration_ms"),
        "confirmation_wait_ms": turn.get("confirmation_wait_ms", 0),
        "first_response_ms": turn.get("first_response_ms"),
        "status": turn.get("status"),
        "provider": last.get("provider") or "",
        "model": last.get("model") or usage.get("model") or "",
        "round_count": len(rounds),
        "tool_call_count": tool_call_count,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": int(usage.get("completion_tokens") or 0),
        "cached_prompt_tokens": cached,
        "cache_hit_percent": round((cached / prompt_tokens) * 100, 1) if prompt_tokens else 0.0,
        "finish_reason": ((last.get("finish") or {}).get("reason") if last else None),
        "response_preview": " ".join(response.split())[:180],
        "prompt_version": turn.get("prompt_version"),
        "prompt_catalog_hash": turn.get("prompt_catalog_hash"),
    }


def list_turns(*, session_id: str | None = None, limit: int = 30) -> list[dict[str, Any]]:
    from yumi.core.platform.storage.privacy_guard import session_erased

    with _lock:
        rows = [row for row in _turns.values() if not session_erased(row.get("session_id", ""))]
        if session_id:
            rows = [row for row in rows if row.get("session_id") == session_id]
        return [copy.deepcopy(_summary(row)) for row in reversed(rows[-max(1, min(100, int(limit))) :])]


def get_turn(turn_id: str) -> dict[str, Any] | None:
    from yumi.core.platform.storage.privacy_guard import session_erased

    with _lock:
        row = _turns.get(turn_id)
        if row is None or session_erased(row.get("session_id", "")):
            return None
        public = copy.deepcopy(row)
    for round_record in public.get("rounds") or []:
        round_record.pop("_started", None)
    public.pop("_started", None)
    public["summary"] = _summary(public)
    return public


def clear_turns() -> None:
    """Clear only the live cache (durable SQLite history is unaffected)."""
    with _lock:
        _turns.clear()
        _active_by_session.clear()


def clear_owner_turns(prefix: str, *, include_groups: bool = False) -> None:
    from yumi.core.platform.storage.assistant_store import is_group_session

    with _lock:
        for key, row in list(_turns.items()):
            sid = row.get("session_id", "")
            if sid.startswith(prefix) and (include_groups or not is_group_session(sid)):
                _turns.pop(key, None)
                _active_by_session.pop(sid, None)


__all__ = [
    "begin_turn",
    "clear_turns",
    "end_turn",
    "get_turn",
    "list_turns",
    "record_finish",
    "record_llm_request",
    "record_routing",
    "record_stream_event",
    "record_tool_calls",
    "record_tool_result",
    "record_usage",
]
