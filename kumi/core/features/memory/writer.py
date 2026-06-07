"""Selective writes for structured long-term memory."""

from __future__ import annotations

import json
import re
from typing import Any

from kumi.core.features.memory.constants import KUMI_V1_TOOL_CALLS, KUMI_V1_TOOL_RESULT

_PREFERENCE_PATTERNS = (re.compile(r"\b(always|prefer|remember that|from now on|by default)\b.{0,120}", re.IGNORECASE),)
_FACT_PATTERNS = (re.compile(r"\b(this project|the project|we use|it uses|is built with)\b.{0,180}", re.IGNORECASE),)
_DECISION_PATTERNS = (re.compile(r"\b(decided|decision|we will|the plan is|conclusion)\b.{0,180}", re.IGNORECASE),)


class MemoryWriter:
    """Turn high-signal events into durable structured memory."""

    def __init__(self, memory: Any):
        self.memory = memory

    def observe_message(self, message: dict) -> None:
        role = message.get("role")
        content = str(message.get("content") or "").strip()
        if not content or content.startswith(KUMI_V1_TOOL_CALLS) or content.startswith(KUMI_V1_TOOL_RESULT):
            return
        if role not in {"user", "assistant"}:
            return

        for kind, extracted, importance in self._extract_candidates(content, role):
            self.memory.create_long_term_memory(
                kind=kind,
                content=extracted,
                session_id=str(message.get("session_id") or self.memory.session_id),
                source_message_ids=[str(message.get("id") or "")],
                confidence=0.65,
                importance=importance,
            )

    def observe_tool_turns(self, messages: list[dict]) -> None:
        pending_name = ""
        pending_args = ""
        call_id = ""
        for m in messages:
            role = m.get("role")
            if role == "assistant" and m.get("tool_calls"):
                calls = m.get("tool_calls") or []
                if calls:
                    call = calls[0]
                    fn = call.get("function") or {}
                    pending_name = str(fn.get("name") or "tool")
                    pending_args = _compact_json(fn.get("arguments"))
                    call_id = str(call.get("id") or "")
            elif role == "tool":
                name = str(m.get("name") or pending_name or "tool")
                content = str(m.get("content") or "")
                self.memory.create_tool_observation(
                    tool_name=name,
                    args_summary=pending_args,
                    result_summary=_summarize_text(content),
                    success=not _looks_like_failure(content),
                    session_id=self.memory.session_id,
                    call_id=call_id,
                    importance=0.75 if _looks_like_failure(content) else 0.55,
                )

    def _extract_candidates(self, content: str, role: str) -> list[tuple[str, str, float]]:
        out: list[tuple[str, str, float]] = []
        if role == "user":
            out.extend(
                ("preference", _trim_match(m.group(0)), 0.9) for p in _PREFERENCE_PATTERNS for m in p.finditer(content)
            )
            out.extend(("fact", _trim_match(m.group(0)), 0.75) for p in _FACT_PATTERNS for m in p.finditer(content))
        out.extend(("decision", _trim_match(m.group(0)), 0.7) for p in _DECISION_PATTERNS for m in p.finditer(content))

        deduped: list[tuple[str, str, float]] = []
        seen: set[tuple[str, str]] = set()
        for kind, text, importance in out:
            if len(text) < 8:
                continue
            key = (kind, text.lower())
            if key in seen:
                continue
            seen.add(key)
            deduped.append((kind, text[:500], importance))
        return deduped[:4]


def _trim_match(text: str) -> str:
    return " ".join(text.strip(" \n\t:.!").split())


def _summarize_text(text: str, max_len: int = 1000) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= max_len:
        return normalized
    return normalized[:max_len] + "..."


def _compact_json(value: Any, max_len: int = 500) -> str:
    if isinstance(value, str):
        raw = value
    else:
        try:
            raw = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except TypeError:
            raw = str(value)
    raw = " ".join(raw.split())
    return raw[:max_len] + ("..." if len(raw) > max_len else "")


def _looks_like_failure(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(marker in lowered for marker in ("error", "exception", "failed", "traceback"))
