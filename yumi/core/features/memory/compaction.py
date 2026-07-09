"""Transcript compaction — fold old turns into the session summary.

The chat context grows append-only (so provider prompt caches hit on every
turn) until the post-watermark transcript exceeds a token budget. Then this
module summarizes the oldest turns into the per-session summary row
(`session_summaries`, which already carries a `covered_until_num` watermark)
and advances the watermark. The transcript fetch in ``context.py`` skips rows
at or below the watermark, so the prompt shrinks by one big block exactly once
per compaction — instead of a sliding window that invalidates the prefix cache
on every single turn and amnesia-drops old messages abruptly.

Failure policy: best-effort. If summarization fails, the transcript simply
keeps growing toward the hard `memory_max_recent_messages` ceiling (the old
sliding behavior) and we retry on a later turn.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from yumi.core.features.config import load_model_config
from yumi.logging_config import get_logger

logger = get_logger(__name__)

_NON_ASCII_RE = re.compile(r"[^\x00-\x7f]")

# Sessions with a compaction currently in flight (single-process asyncio).
_IN_FLIGHT: set[str] = set()

_SUMMARY_PROMPT = """You maintain the running summary of a long, ongoing conversation between a user and their assistant.

PREVIOUS SUMMARY (may be empty):
{previous}

OLDEST MESSAGES BEING FOLDED IN (they will disappear from the visible transcript — your summary is their only trace):
{transcript}

Write the UPDATED summary that merges both. Keep, with priority:
1. Durable facts about the user (preferences, situation, decisions made).
2. Open tasks, commitments, and unresolved questions.
3. Key outcomes of tool actions (things created/changed, ids if referenced later).
4. The current topic thread, so the conversation can continue naturally.

Rules: at most 250 words. Plain text, no headings. Write in the conversation's dominant language. Output ONLY the summary text."""


def estimate_tokens(text: str) -> int:
    """Cheap mixed-script token estimate: CJK ≈ 1 token per ~1.5 chars,
    ASCII ≈ 1 per ~4 chars. Precision is unimportant — this only decides
    when to compact."""
    if not text:
        return 0
    non_ascii = len(_NON_ASCII_RE.findall(text))
    ascii_chars = len(text) - non_ascii
    return int(non_ascii / 1.5 + ascii_chars / 4) + 1


def _row_text(row: dict[str, Any]) -> str:
    return f"{row.get('role') or ''}: {row.get('content') or ''}"


def transcript_token_estimate(rows: list[dict[str, Any]]) -> int:
    return sum(estimate_tokens(_row_text(r)) for r in rows)


def _fetch_rows_after(memory: Any, watermark_num: int, cap: int) -> list[dict[str, Any]]:
    """Current-session rows strictly after the watermark, oldest → newest."""
    sqlite = getattr(memory, "sqlite", None)
    rows: list[dict[str, Any]] = []
    if sqlite is not None:
        try:
            rows = sqlite.recent_transcript_rows(memory.session_id, cap)
        except Exception:
            rows = []
    if not rows:
        return []
    return [
        r for r in rows
        if r.get("session_id") == memory.session_id and int(r.get("timestamp_num") or 0) > watermark_num
    ]


def _render_for_summary(rows: list[dict[str, Any]], *, per_row_chars: int = 400, max_chars: int = 24000) -> str:
    lines: list[str] = []
    total = 0
    for row in rows:
        content = " ".join(str(row.get("content") or "").split())
        if not content:
            continue
        line = f"[{row.get('role') or '?'}] {content[:per_row_chars]}"
        total += len(line)
        if total > max_chars:
            break
        lines.append(line)
    return "\n".join(lines)


def _cut_index(rows: list[dict[str, Any]], keep_tail: int) -> int | None:
    """Index where the kept tail starts. Prefer a boundary where the tail
    begins with a user message so no assistant/tool pair is split."""
    if len(rows) <= keep_tail:
        return None
    cut = len(rows) - keep_tail
    # Walk forward (shrinking the tail) until the tail starts at a user row.
    for i in range(cut, len(rows)):
        if rows[i].get("role") == "user":
            return i
    return cut


async def _summarize(bot: Any, prompt_text: str) -> str:
    full = ""
    async for chunk in bot.provider.chat_stream(
        model=bot.model_name,
        messages=[{"role": "user", "content": prompt_text}],
        tools=None,
        think=False,
    ):
        if chunk.get("type") == "text":
            full += str(chunk.get("content") or "")
    return " ".join(full.split()).strip()


async def compact_session_if_needed(bot: Any, session_id: str) -> bool:
    """Fold the oldest post-watermark turns into the session summary when the
    transcript exceeds the configured token budget. Returns True if a
    compaction ran."""
    cfg = load_model_config()
    if not getattr(cfg, "memory_compaction_enabled", True):
        return False
    budget = int(getattr(cfg, "memory_transcript_token_budget", 8000))
    keep_tail = int(getattr(cfg, "memory_compaction_keep_tail_messages", 16))
    hard_cap = max(1, min(500, int(cfg.memory_max_recent_messages)))

    memory = bot.session_memory(session_id)
    summary_row = memory.get_session_summary(session_id) or {}
    watermark = int(summary_row.get("covered_until_num") or 0)
    previous_summary = str(summary_row.get("summary") or "").strip()

    rows = _fetch_rows_after(memory, watermark, hard_cap * 2)
    if not rows:
        return False
    if transcript_token_estimate(rows) <= budget:
        return False

    cut = _cut_index(rows, keep_tail)
    if cut is None or cut <= 0:
        return False
    head, tail_first = rows[:cut], rows[cut]

    rendered = _render_for_summary(head)
    if not rendered:
        return False
    prompt = _SUMMARY_PROMPT.format(
        previous=previous_summary or "(none)",
        transcript=rendered,
    )
    try:
        new_summary = await _summarize(bot, prompt)
    except Exception as exc:
        logger.warning("Transcript compaction summarize failed for %s: %s", session_id, exc)
        return False
    if not new_summary:
        logger.warning("Transcript compaction produced an empty summary for %s — skipped", session_id)
        return False

    new_watermark = int(head[-1].get("timestamp_num") or 0)
    if new_watermark <= watermark:
        return False
    memory.update_session_summary(new_summary[:6000], session_id=session_id, covered_until_num=new_watermark)
    logger.info(
        "Compacted session %s: folded %d message(s) into the summary (watermark %d → %d, tail keeps %d rows from %s)",
        session_id,
        len(head),
        watermark,
        new_watermark,
        len(rows) - cut,
        tail_first.get("timestamp") or "?",
    )
    return True


def schedule_compaction(session_id: str) -> None:
    """Fire-and-forget compaction check after a chat turn. Never raises."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if session_id in _IN_FLIGHT:
        return
    _IN_FLIGHT.add(session_id)

    async def _run() -> None:
        try:
            from yumi.core.platform.plugins import get_bot_pool, get_session_scope

            owner = get_session_scope().owner_user_from_session_id(session_id)
            bot = await get_bot_pool().get_bot_for_session_owner(owner)
            await compact_session_if_needed(bot, session_id)
        except Exception as exc:
            logger.debug("Scheduled compaction for %s skipped: %s", session_id, exc)
        finally:
            _IN_FLIGHT.discard(session_id)

    loop.create_task(_run())


__all__ = [
    "compact_session_if_needed",
    "estimate_tokens",
    "schedule_compaction",
    "transcript_token_estimate",
]
