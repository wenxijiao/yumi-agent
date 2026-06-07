"""Hybrid retrieval for transcript, long-term memories, and tool observations."""

from __future__ import annotations

import math
import re
from typing import Any

from yumi.core.features.memory.embedding_state import is_degenerate_vector
from yumi.core.features.memory.models import MemoryCandidate

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def tokenize(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if t.strip()}


def keyword_score(query: str, content: str) -> float:
    q_tokens = tokenize(query)
    if not q_tokens:
        return 0.0
    c = (content or "").lower()
    direct = 0.35 if query.strip().lower() in c else 0.0
    c_tokens = tokenize(content)
    overlap = len(q_tokens & c_tokens) / max(len(q_tokens), 1)
    return min(1.0, direct + overlap)


def recency_score(timestamp_num: int, now_num: int) -> float:
    if timestamp_num <= 0:
        return 0.0
    age_days = max(0.0, (now_num - timestamp_num) / 86_400_000)
    return math.exp(-age_days / 30.0)


def kind_boost(kind: str, query: str) -> float:
    q = query.lower()
    if kind == "preference":
        return 0.25
    if kind == "tool_observation" and any(word in q for word in ("tool", "call", "result", "failure", "error")):
        return 0.3
    if kind in {"decision", "task_state"} and any(
        word in q for word in ("continue", "last", "state", "decision", "todo", "status")
    ):
        return 0.2
    return 0.0


class HybridRetriever:
    """Combine semantic, lexical, recency, and importance signals."""

    def __init__(self, memory: Any):
        self.memory = memory

    def transcript(self, query: str, *, session_id: str | None, limit: int) -> list[dict]:
        return self.memory._legacy_search_messages(query=query, session_id=session_id, limit=limit)

    def structured(self, query: str, *, limit: int = 8) -> list[MemoryCandidate]:
        candidates: list[MemoryCandidate] = []
        candidates.extend(self._long_term_candidates(query, limit=limit * 2))
        candidates.extend(self._tool_candidates(query, limit=limit * 2))
        ranked = self.rank(query, candidates)
        return ranked[:limit]

    def rank(self, query: str, candidates: list[MemoryCandidate]) -> list[MemoryCandidate]:
        now = self.memory._current_timestamp_num()
        ranked: list[MemoryCandidate] = []
        for c in candidates:
            score = (
                c.score
                + 0.35 * keyword_score(query, c.content)
                + 0.15 * recency_score(c.timestamp_num, now)
                + 0.25 * max(0.0, min(1.0, c.importance))
                + kind_boost(c.kind, query)
            )
            ranked.append(
                MemoryCandidate(
                    id=c.id,
                    kind=c.kind,
                    content=c.content,
                    source=c.source,
                    session_id=c.session_id,
                    timestamp=c.timestamp,
                    timestamp_num=c.timestamp_num,
                    score=score,
                    importance=c.importance,
                    metadata=c.metadata,
                )
            )
        ranked.sort(key=lambda item: item.score, reverse=True)
        return _dedupe_candidates(ranked)

    def _long_term_candidates(self, query: str, *, limit: int) -> list[MemoryCandidate]:
        rows = self.memory._search_structured_table(
            self.memory.long_term_table_name,
            query,
            limit=limit,
            content_field="content",
        )
        return [
            MemoryCandidate(
                id=str(row.get("id") or ""),
                kind=str(row.get("kind") or "fact"),
                content=str(row.get("content") or ""),
                source="long_term",
                session_id=str(row.get("session_id") or ""),
                timestamp=str(row.get("updated_at") or row.get("created_at") or ""),
                timestamp_num=int(row.get("updated_at_num") or row.get("created_at_num") or 0),
                score=float(row.get("_score") or 0.0),
                importance=float(row.get("importance") or 0.0),
                metadata={"confidence": float(row.get("confidence") or 0.0)},
            )
            for row in rows
            if str(row.get("content") or "").strip()
        ]

    def _tool_candidates(self, query: str, *, limit: int) -> list[MemoryCandidate]:
        rows = self.memory._search_structured_table(
            self.memory.tool_observation_table_name,
            query,
            limit=limit,
            content_field="content",
        )
        out: list[MemoryCandidate] = []
        for row in rows:
            content = str(row.get("content") or row.get("result_summary") or "")
            if not content.strip():
                continue
            out.append(
                MemoryCandidate(
                    id=str(row.get("id") or ""),
                    kind="tool_observation",
                    content=content,
                    source="tool",
                    session_id=str(row.get("session_id") or ""),
                    timestamp=str(row.get("timestamp") or ""),
                    timestamp_num=int(row.get("timestamp_num") or 0),
                    score=float(row.get("_score") or 0.0),
                    importance=float(row.get("importance") or 0.0),
                    metadata={
                        "tool_name": str(row.get("tool_name") or ""),
                        "success": bool(row.get("success", True)),
                    },
                )
            )
        return out


def _dedupe_candidates(candidates: list[MemoryCandidate]) -> list[MemoryCandidate]:
    seen: set[tuple[str, str, str]] = set()
    out: list[MemoryCandidate] = []
    for c in candidates:
        key = (c.kind, c.session_id, " ".join(c.content.lower().split())[:240])
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def vector_available(memory: Any, query_vector: list | tuple | None) -> bool:
    return bool(memory.embed_model and memory._embedding_available and not is_degenerate_vector(query_vector))
