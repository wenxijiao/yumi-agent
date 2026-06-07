"""Structured memory model constants and serializers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

LONG_TERM_MEMORY_KINDS = frozenset(
    {
        "preference",
        "fact",
        "decision",
        "task_state",
        "tool_observation",
        "summary",
    }
)

LONG_TERM_TABLE = "long_term_memories"
TOOL_OBSERVATION_TABLE = "tool_observations"
SESSION_SUMMARY_TABLE = "session_summaries"


@dataclass(slots=True)
class MemoryCandidate:
    """A retrievable unit before prompt formatting."""

    id: str
    kind: str
    content: str
    source: str
    session_id: str
    timestamp: str
    timestamp_num: int
    score: float
    importance: float = 0.0
    metadata: dict[str, Any] | None = None


def encode_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def decode_json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def decode_json_list(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    return value if isinstance(value, list) else []
