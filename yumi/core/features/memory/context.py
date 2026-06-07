"""Prompt context assembly for Yumi memory."""

from __future__ import annotations

import json
from typing import Any

from yumi.core.features.config import load_model_config
from yumi.core.features.memory.constants import YUMI_V1_TOOL_CALLS, YUMI_V1_TOOL_RESULT
from yumi.core.features.memory.retrieval import HybridRetriever
from yumi.core.features.memory.transcript import (
    dedupe_consecutive_user_rows,
    trim_leading_orphan_assistant_tool_calls,
    trim_leading_orphan_tool_rows,
    trim_trailing_incomplete_tool_rows,
)

# Channel labels rendered into peer-session user/assistant rows so the model can
# distinguish "where" a recent turn happened. Keyed by session-id prefix.
_CHANNEL_LABELS = {
    "voice_": "voice",
    "tg_": "telegram",
    "chat_": "chat",
}


def _channel_label(session_id: str | None) -> str | None:
    if not session_id:
        return None
    for prefix, label in _CHANNEL_LABELS.items():
        if session_id.startswith(prefix):
            return label
    return None


class ContextBuilder:
    """Build OpenAI-style messages from memory layers."""

    def __init__(self, memory: Any):
        self.memory = memory
        self.retriever = HybridRetriever(memory)

    def build(
        self,
        query: str | None = None,
        max_cross_session: int | None = None,
        peer_session_ids: list[str] | None = None,
    ) -> list[dict]:
        cfg = load_model_config()
        max_recent = max(1, min(500, int(cfg.memory_max_recent_messages)))
        if max_cross_session is None:
            max_cross = max(0, min(100, int(cfg.memory_max_related_messages)))
        else:
            max_cross = max(0, min(100, int(max_cross_session)))

        formatted_messages = [self.memory.get_system_message()]
        if query:
            structured = self._structured_memory_message(query, limit=max_cross)
            if structured:
                formatted_messages.append(structured)

            summary = self._session_summary_message()
            if summary:
                formatted_messages.append(summary)
        elif self._session_summary_message():
            formatted_messages.append(self._session_summary_message())

        if query and max_cross > 0:
            related = self.memory.build_related_memory_message(
                query, exclude_session_id=self.memory.session_id, limit=max_cross
            )
            if related:
                formatted_messages.append(related)

        formatted_messages.extend(self._recent_transcript(max_recent, peer_session_ids))
        return formatted_messages

    def _session_summary_message(self) -> dict | None:
        row = self.memory.get_session_summary(self.memory.session_id)
        if not row:
            return None
        summary = str(row.get("summary") or "").strip()
        if not summary:
            return None
        return {
            "role": "system",
            "content": f"Current session summary:\n{summary}",
        }

    def _structured_memory_message(self, query: str, *, limit: int) -> dict | None:
        if limit <= 0:
            return None
        candidates = self.retriever.structured(query, limit=min(12, max(4, limit)))
        if not candidates:
            return None
        lines = ["Structured memory likely relevant to this request:"]
        for c in candidates:
            prefix = c.kind.replace("_", " ")
            source = f"{c.source}:{c.session_id}" if c.session_id else c.source
            lines.append(f"- [{prefix}; {source}; score={c.score:.2f}] {c.content[:500]}")
        return {"role": "system", "content": "\n".join(lines)}

    def _recent_transcript(
        self,
        max_recent: int,
        peer_session_ids: list[str] | None = None,
    ) -> list[dict]:
        if not self.memory._table_exists():
            return []

        table = self.memory._open_table()
        where_clause = self.memory._build_where_clause("session_id", self.memory.session_id)
        total_messages = table.count_rows(where_clause)
        offset = max(total_messages - max_recent, 0)
        limit = max_recent

        base = table.search(query=None, ordering_field_name="timestamp_num").where(where_clause)

        def _fetch_window() -> list[dict]:
            return base.offset(offset).limit(limit).to_list()

        results = _fetch_window()
        guard = 0
        while results and results[0].get("role") == "tool" and offset > 0 and guard < 48:
            step = min(64, offset)
            offset -= step
            limit += step
            results = _fetch_window()
            guard += 1

        peer_rows: list[dict] = []
        if peer_session_ids:
            try:
                peer_rows = self.memory.recent_messages_in_sessions(peer_session_ids, max_recent)
            except Exception:
                peer_rows = []
            # Peer tool rows reference tool_call_ids that don't exist in the current
            # session's assistant messages — they would only confuse the model and
            # break strict OpenAI replay rules. Drop them entirely.
            peer_rows = [r for r in peer_rows if r.get("role") in {"user", "assistant"}]

        if peer_rows:
            current_sid = self.memory.session_id
            seen_ids = {r.get("id") for r in results if r.get("id")}
            for row in peer_rows:
                rid = row.get("id")
                if rid and rid in seen_ids:
                    continue
                seen_ids.add(rid)
                results.append(row)
            results.sort(key=lambda r: int(r.get("timestamp_num") or 0))
            # Keep the tail; allow modest extra room so peers don't crowd out own rows.
            cap = max_recent + max_recent  # at most 2x own window after merge
            if len(results) > cap:
                results = results[-cap:]
            # Mark which rows belong to peer sessions so the formatter can tag them.
            for r in results:
                if r.get("session_id") and r.get("session_id") != current_sid:
                    r["_peer_channel"] = _channel_label(r.get("session_id"))

        results = trim_leading_orphan_tool_rows(results)
        results = trim_trailing_incomplete_tool_rows(results)
        if offset > 0:
            # Only strip orphaned assistant tool-calls when the sliding window
            # actually cut off earlier rows — i.e. the triggering user prompt
            # is genuinely gone.  When the whole session fits in the window,
            # preserve the row (a malformed session without a user prompt is
            # a separate concern handled by callers/tests).
            results = trim_leading_orphan_assistant_tool_calls(results)
        results = dedupe_consecutive_user_rows(results)
        return [_format_transcript_message(msg) for msg in results]


def _format_transcript_message(msg: dict) -> dict:
    raw = msg.get("content") or ""
    peer_channel = msg.get("_peer_channel")
    if msg["role"] == "assistant":
        if raw.startswith(YUMI_V1_TOOL_CALLS):
            try:
                data = json.loads(raw[len(YUMI_V1_TOOL_CALLS) :])
                tcalls = data.get("tool_calls")
                if isinstance(tcalls, list) and tcalls:
                    out = {
                        "role": "assistant",
                        "content": data.get("content", ""),
                        "tool_calls": tcalls,
                    }
                    # Restore the provider's chain-of-thought when one was
                    # persisted — DeepSeek thinking models require it on
                    # replay whenever the assistant turn carried tool_calls.
                    reasoning = data.get("reasoning_content")
                    if isinstance(reasoning, str) and reasoning:
                        out["reasoning_content"] = reasoning
                    return out
            except (json.JSONDecodeError, TypeError):
                pass
        if peer_channel:
            return {"role": "assistant", "content": f"(via {peer_channel}) {raw}"}
        return {"role": "assistant", "content": raw}
    if msg["role"] == "user":
        if peer_channel:
            return {"role": "user", "content": f"[{msg['timestamp']}] (via {peer_channel}) {raw}"}
        return {"role": "user", "content": f"[{msg['timestamp']}] {raw}"}
    if msg["role"] == "tool":
        if raw.startswith(YUMI_V1_TOOL_RESULT):
            try:
                data = json.loads(raw[len(YUMI_V1_TOOL_RESULT) :])
                return {"role": "tool", "name": data.get("name") or "tool", "content": str(data.get("content", ""))}
            except (json.JSONDecodeError, TypeError):
                return {"role": "tool", "name": "tool", "content": raw}
        return {"role": "tool", "name": "tool", "content": raw}
    return {"role": msg["role"], "content": raw}
