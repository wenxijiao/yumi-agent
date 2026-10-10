"""Hybrid, permission-scoped capability retrieval with an explicit degraded state.

Registration warms metadata vectors. Chat never builds an entire remote index on
its critical path; missing vectors leave lexical retrieval and catalog browsing
available. No business tool runs during selection.
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextvars import copy_context
from dataclasses import dataclass
from threading import BoundedSemaphore

from yumi.core.platform.tools.routing import (
    ToolCatalogEntry,
    _cached_embedding,
    _cosine_similarity,
    _query_mentions_edge,
    _score_edge_tools_lexical,
)

# Small offline vocabulary for common capabilities, not app/tool/artist names.
# This is a fallback, not a claim of universal cross-language semantic search.
_CAPABILITY_ALIASES = {
    "music song search play": (
        "音乐",
        "音樂",
        "听歌",
        "聽歌",
        "想听",
        "想聽",
        "放歌",
        "放首",
        "音楽",
        "聴きたい",
        "聞きたい",
        "ききたい",
        "曲を",
        "曲が",
        "流して",
    ),
    "play playback": ("播放", "再生"),
    "light lamp brightness": ("开灯", "開燈", "关灯", "關燈", "灯光", "燈光", "亮度", "照明"),
    "timer reminder schedule": ("提醒", "定时", "定時", "闹钟", "鬧鐘", "リマインダー"),
    "create reminder notification schedule": ("remind me", "set a reminder", "提醒我", "提醒一下"),
    "note search": ("笔记", "筆記", "ノート"),
    "weather forecast": ("天气", "天氣", "天気"),
    "file read": ("文件", "档案", "檔案", "ファイル"),
}
_STOPWORDS = re.compile(r"\b(?:i|a|an|the|to|for|of|in|on|my|me|please|want|would|like|can|you|could|some)\b", re.I)

# Retrieval is optional preparation, not a reason to wait for a provider's full
# HTTP timeout/retry cycle. A separate bounded pool prevents timed-out providers
# from consuming the chat executor or creating an unbounded queue of work.
INITIAL_SEMANTIC_BUDGET_SECONDS = 0.75
DISCOVERY_SEMANTIC_BUDGET_SECONDS = 1.0
_SEMANTIC_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tool-retrieval")
_SEMANTIC_SLOTS = BoundedSemaphore(4)


def capability_query(query: str) -> str:
    additions = [words for words, aliases in _CAPABILITY_ALIASES.items() if any(a in query.casefold() for a in aliases)]
    return _STOPWORDS.sub(" ", " ".join([query, *additions])).strip()


@dataclass
class RankedTools:
    matches: list[tuple[float, ToolCatalogEntry]]
    mode: str
    degraded: bool = False
    degraded_reason: str = ""
    elapsed_ms: int = 0


def _safe_embedding(model: str, text: str, **kwargs) -> list[float] | None:
    try:
        return _cached_embedding(model, text, **kwargs)
    except Exception:
        # Provider initialization and cache failures are also degraded retrieval,
        # not an empty catalog. The caller reports this state explicitly.
        return None


def _semantic_scores(query, entries, model, deadline):
    documents = []
    missing = False
    # Do not spend a query request when the metadata index is entirely cold.
    # Disk/cache I/O shares the deadline with the remote call.
    for entry in entries:
        if time.monotonic() >= deadline:
            return [], "timeout"
        doc = _safe_embedding(model, entry.search_text, persistent=True, cache_only=True)
        if doc is None:
            missing = True
        else:
            documents.append((entry, doc))
    if not documents:
        return [], "index_incomplete"
    if time.monotonic() >= deadline:
        return [], "timeout"
    vector = _safe_embedding(model, query)
    if vector is None:
        return [], "unavailable"
    if time.monotonic() >= deadline:
        return [], "timeout"
    scores = []
    for entry, doc in documents:
        if len(doc) != len(vector):
            missing = True
            continue
        score = _cosine_similarity(vector, doc)
        if score >= 0.3:
            scores.append((score, entry))
    scores.sort(key=lambda pair: (-pair[0], pair[1].name))
    return scores, "index_incomplete" if missing else ""


def _bounded_semantic_scores(query, entries, model, budget):
    if budget <= 0 or not _SEMANTIC_SLOTS.acquire(blocking=False):
        return [], "busy"
    slots = _SEMANTIC_SLOTS
    deadline = time.monotonic() + budget
    try:
        future = _SEMANTIC_POOL.submit(copy_context().run, _semantic_scores, query, entries, model, deadline)
    except Exception:
        slots.release()
        return [], "unavailable"
    future.add_done_callback(lambda _: slots.release())
    try:
        return future.result(timeout=max(0, deadline - time.monotonic()))
    except TimeoutError:
        # Running sync provider calls cannot be killed. They retain a slot until
        # completion, so subsequent requests degrade promptly instead of queueing.
        return [], "timeout"
    except Exception:
        return [], "unavailable"


def rank_tools(
    query: str,
    entries: list[ToolCatalogEntry],
    *,
    embed_model: str | None,
    semantic_budget: float = DISCOVERY_SEMANTIC_BUDGET_SECONDS,
) -> RankedTools:
    """Fuse lexical and semantic ranks; exact names cannot be lost to embeddings."""
    started = time.monotonic()
    semantic_query = query
    query = capability_query(query)
    entries = [e for e in entries if e.name not in {"discover_app_tools", "browse_app_tools"}]
    if not entries or not query:
        return RankedTools([], "lexical")
    lexical = [(s, e) for s, e in _score_edge_tools_lexical(query, entries) if s > 0]
    semantic, reason = (
        _bounded_semantic_scores(semantic_query, entries, embed_model, semantic_budget) if embed_model else ([], "")
    )
    scores: dict[str, float] = {}
    for ranking in (lexical, semantic):
        for rank, (_, entry) in enumerate(ranking):
            scores[entry.name] = scores.get(entry.name, 0) + 1 / (20 + rank)
    for entry in entries:
        if entry.name.lower() in query.lower():
            scores[entry.name] = scores.get(entry.name, 0) + 1
        elif entry.kind == "edge" and _query_mentions_edge(query, entry):
            scores[entry.name] = scores.get(entry.name, 0) + 0.1
    ordered = sorted(
        ((scores[e.name], e) for e in entries if e.name in scores), key=lambda pair: (-pair[0], pair[1].name)
    )
    return RankedTools(
        ordered,
        "hybrid" if embed_model and (semantic or not reason) else "lexical",
        bool(reason),
        reason,
        int((time.monotonic() - started) * 1000),
    )


def with_companions(selected: list[ToolCatalogEntry], visible: list[ToolCatalogEntry]) -> list[ToolCatalogEntry]:
    """Keep bounded same-device prerequisites and follow-up functions.

    Exact references work in both directions (search -> play as well as play ->
    search). create/add_RESOURCE also keeps update/get_RESOURCE for corrections.
    This loads metadata only; authorization and confirmation remain unchanged.
    One hop and two companions per match avoid expanding an entire device.
    """
    out: list[ToolCatalogEntry] = []
    seen: set[str] = set()
    references = {e.name: set(re.findall(r"\b[A-Za-z][A-Za-z0-9_]*\b", e.description)) for e in visible}
    for entry in selected:
        short_name = entry.name.rsplit("__", 1)[-1]
        creation = re.fullmatch(r"(?:create|add)_(.+)", short_name)
        followups = {f"{verb}_{creation[1]}" for verb in ("update", "get")} if creation else set()
        siblings = [
            other
            for other in visible
            if other.name != entry.name and (other.kind, other.edge_key) == (entry.kind, entry.edge_key)
        ]
        prerequisites = [e for e in siblings if {e.name, e.name.rsplit("__", 1)[-1]} & references[entry.name]]
        dependants = [
            e
            for e in siblings
            if {entry.name, short_name} & references[e.name] or e.name.rsplit("__", 1)[-1] in followups
        ]
        companions = sorted(prerequisites, key=lambda e: e.name) + sorted(
            dependants, key=lambda e: (e.name.rsplit("__", 1)[-1] not in followups, e.name)
        )
        companions = list({e.name: e for e in companions}.values())
        # Admit the selected function before optional follow-ups; don't displace
        # it with reverse references from large sibling schemas.
        for item in [entry, *companions[:2]]:
            if item.name not in seen:
                seen.add(item.name)
                out.append(item)
    return out
