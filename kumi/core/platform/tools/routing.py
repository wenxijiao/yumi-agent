"""Tool cataloging and routing for Kumi chat requests.

Core Kumi tools stay loaded on every turn. Edge tools can scale into the
hundreds or thousands, so they are ranked against the current request and only
the most relevant schemas are exposed to the model.
"""

import math
import re
import threading
import time
import uuid
from collections import Counter, deque
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from kumi.core.platform.plugins import get_current_identity, get_edge_scope
from kumi.core.platform.runtime.tool_catalog import model_visible_tool_schema
from kumi.core.platform.tools.tool import TOOL_REGISTRY
from kumi.logging_config import get_logger

logger = get_logger(__name__)


# Lazy seams to the config + memory features. Routing (platform) needs the
# embedding provider and model config, but importing those features at module
# load would make platform depend on features. These thin module-level wrappers
# defer the import to call time (keeping platform import-clean) while remaining
# patchable module attributes for tests.
def load_model_config():
    from kumi.core.features.config import load_model_config as _impl

    return _impl()


def get_embed_provider():
    from kumi.core.features.memory.embedding_state import get_embed_provider as _impl

    return _impl()


def is_degenerate_vector(vec) -> bool:
    from kumi.core.features.memory.embedding_state import is_degenerate_vector as _impl

    return _impl(vec)


_MAX_ROUTING_TRACES = 1000
_ROUTING_TRACES: deque[dict[str, Any]] = deque(maxlen=_MAX_ROUTING_TRACES)
_ROUTING_TRACE_LOCK = threading.Lock()
_EMBED_CACHE_MAX = 5000
_EMBED_CACHE: dict[tuple[str, str, str], list[float]] = {}
_EMBED_CACHE_ORDER: deque[tuple[str, str, str]] = deque(maxlen=_EMBED_CACHE_MAX)
_EMBED_CACHE_LOCK = threading.Lock()

_TOKEN_RE = re.compile(r"[\w.-]+", re.UNICODE)
_NON_ASCII_RE = re.compile(r"[^\x00-\x7f]")


@dataclass(frozen=True)
class ToolCatalogEntry:
    """A normalized view of one callable tool."""

    name: str
    kind: str
    schema: dict[str, Any]
    description: str
    parameters_text: str
    namespace: str = ""
    edge_key: str | None = None
    device_name: str = ""
    device_aliases: tuple[str, ...] = ()
    enabled: bool = True
    always_include: bool = False

    @property
    def search_text(self) -> str:
        if self.kind == "edge":
            return "\n".join(
                part
                for part in (
                    f"Device name: {self.device_name}" if self.device_name else "",
                    f"Device aliases: {', '.join(self.device_aliases)}" if self.device_aliases else "",
                    f"Device namespace: {self.namespace}" if self.namespace else "",
                    f"Tool name: {self.name}",
                    f"Tool description: {self.description}" if self.description else "",
                    f"Tool parameters: {self.parameters_text}" if self.parameters_text else "",
                )
                if part
            )
        return " ".join(part for part in (self.name, self.namespace, self.description, self.parameters_text) if part)

    @property
    def device_text(self) -> str:
        return " ".join(
            part
            for part in (
                self.device_name,
                self.namespace,
                " ".join(self.device_aliases),
                self.edge_key or "",
            )
            if part
        )


@dataclass(frozen=True)
class ToolRoutingDecision:
    """The schemas selected for one model request."""

    tools: list[dict[str, Any]]
    core_tools: list[ToolCatalogEntry]
    selected_edge_tools: list[ToolCatalogEntry]
    total_edge_tools: int
    dynamic_routing_enabled: bool
    elapsed_ms: int


def _tool_name(schema: dict[str, Any]) -> str:
    fn = schema.get("function") if isinstance(schema, dict) else None
    if not isinstance(fn, dict):
        return ""
    return str(fn.get("name") or "")


def _tool_description(schema: dict[str, Any]) -> str:
    fn = schema.get("function") if isinstance(schema, dict) else None
    if not isinstance(fn, dict):
        return ""
    return str(fn.get("description") or "")


def _parameter_text(schema: dict[str, Any]) -> str:
    fn = schema.get("function") if isinstance(schema, dict) else None
    if not isinstance(fn, dict):
        return ""
    params = fn.get("parameters")
    if not isinstance(params, dict):
        return ""

    parts: list[str] = []
    properties = params.get("properties")
    if isinstance(properties, dict):
        for name, prop in properties.items():
            parts.append(str(name))
            if isinstance(prop, dict):
                desc = prop.get("description")
                if desc:
                    parts.append(str(desc))
                enum = prop.get("enum")
                if isinstance(enum, list):
                    parts.extend(str(v) for v in enum[:10])

    required = params.get("required")
    if isinstance(required, list):
        parts.extend(str(v) for v in required)
    return " ".join(parts)


def _edge_display_name(edge_key: str) -> str:
    key = str(edge_key or "").strip()
    if key.startswith("u:"):
        _, _, rest = key.partition("::")
        if rest:
            return rest
    return key


def _edge_segment_from_tool_name(tool_name: str) -> str:
    if not tool_name.startswith("edge_") or "__" not in tool_name:
        return ""
    rest = tool_name[5:]
    segment, _, _ = rest.partition("__")
    return segment


def _split_alias_terms(value: str) -> list[str]:
    raw = str(value or "").strip()
    if not raw:
        return []
    terms = [raw]
    spaced = re.sub(r"[_:/.-]+", " ", raw).strip()
    if spaced and spaced != raw:
        terms.append(spaced)
    compact = re.sub(r"[_\s:/.-]+", "", raw).strip()
    if compact and compact not in terms:
        terms.append(compact)
    return terms


def _edge_aliases(edge_key: str, tool_name: str) -> tuple[str, ...]:
    aliases: list[str] = []
    for value in (_edge_display_name(edge_key), _edge_segment_from_tool_name(tool_name), edge_key):
        aliases.extend(_split_alias_terms(value))

    seen: set[str] = set()
    out: list[str] = []
    for alias in aliases:
        folded = alias.casefold()
        if not alias or folded in seen:
            continue
        seen.add(folded)
        out.append(alias)
    return tuple(out)


def _tokens(text: str) -> list[str]:
    out: list[str] = []
    for match in _TOKEN_RE.finditer(text or ""):
        token = match.group(0).lower()
        out.append(token)
        if _NON_ASCII_RE.search(token):
            chars = [ch for ch in token if not ch.isspace()]
            out.extend(chars)
            out.extend("".join(pair) for pair in zip(chars, chars[1:]))
    return out


def _name_terms(name: str) -> list[str]:
    out: list[str] = []
    for part in re.split(r"[_\W]+", name or ""):
        part = part.strip().lower()
        if part:
            out.append(part)
    return out


def _cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    a_norm = 0.0
    b_norm = 0.0
    for x, y in zip(a, b):
        fx = float(x)
        fy = float(y)
        dot += fx * fy
        a_norm += fx * fx
        b_norm += fy * fy
    if a_norm <= 0.0 or b_norm <= 0.0:
        return 0.0
    return dot / ((a_norm**0.5) * (b_norm**0.5))


def _cached_embedding(model: str, text: str) -> list[float] | None:
    provider = get_embed_provider()
    if provider is None or not model or not text.strip():
        return None

    key = (model, str(hash(text)), text[:128])
    with _EMBED_CACHE_LOCK:
        cached = _EMBED_CACHE.get(key)
        if cached is not None:
            return cached

    try:
        vec = provider.embed(model, text)
    except Exception as exc:
        logger.debug("Tool routing embedding failed: %s", exc)
        return None

    if is_degenerate_vector(vec):
        return None

    out = [float(v) for v in vec]
    with _EMBED_CACHE_LOCK:
        if key not in _EMBED_CACHE:
            if len(_EMBED_CACHE_ORDER) >= _EMBED_CACHE_MAX:
                old = _EMBED_CACHE_ORDER.popleft()
                _EMBED_CACHE.pop(old, None)
            _EMBED_CACHE[key] = out
            _EMBED_CACHE_ORDER.append(key)
    return out


def _score_edge_tools_with_embeddings(
    query: str,
    entries: list[ToolCatalogEntry],
    *,
    embed_model: str | None,
) -> list[tuple[float, ToolCatalogEntry]] | None:
    if not embed_model or not query.strip() or not entries:
        return None

    query_vec = _cached_embedding(embed_model, query)
    if query_vec is None:
        return None

    scored: list[tuple[float, ToolCatalogEntry]] = []
    for entry in entries:
        doc_vec = _cached_embedding(embed_model, entry.search_text)
        if doc_vec is None:
            return None
        score = _cosine_similarity(query_vec, doc_vec)
        device_vec = _cached_embedding(embed_model, entry.device_text) if entry.device_text else None
        if device_vec is not None:
            score = (0.8 * score) + (0.2 * _cosine_similarity(query_vec, device_vec))
        scored.append((score, entry))

    scored.sort(key=lambda item: (-item[0], item[1].name))
    return scored


def _score_edge_tools_lexical(query: str, entries: list[ToolCatalogEntry]) -> list[tuple[float, ToolCatalogEntry]]:
    query_tokens = _tokens(query)
    if not query_tokens:
        return [(0.0, entry) for entry in entries]

    query_counts = Counter(query_tokens)
    doc_tokens_by_name: dict[str, list[str]] = {}
    df: Counter[str] = Counter()
    for entry in entries:
        toks = _tokens(entry.search_text)
        doc_tokens_by_name[entry.name] = toks
        df.update(set(toks))

    total_docs = max(1, len(entries))
    scored: list[tuple[float, ToolCatalogEntry]] = []
    lower_query = (query or "").lower()

    for entry in entries:
        toks = doc_tokens_by_name.get(entry.name) or []
        if not toks:
            scored.append((0.0, entry))
            continue

        doc_counts = Counter(toks)
        doc_len = max(1, len(toks))
        bm25 = 0.0
        for tok, qtf in query_counts.items():
            tf = doc_counts.get(tok, 0)
            if not tf:
                continue
            idf = math.log(1 + (total_docs - df[tok] + 0.5) / (df[tok] + 0.5))
            bm25 += qtf * idf * ((tf * 2.2) / (tf + 1.2 * (0.25 + 0.75 * doc_len / 80)))

        name = entry.name.lower()
        name_bonus = 0.0
        if name and name in lower_query:
            name_bonus += 8.0
        name_terms = set(_name_terms(entry.name))
        overlap = name_terms.intersection(query_counts)
        if overlap:
            name_bonus += 2.5 * len(overlap)

        namespace_bonus = 0.0
        namespace = (entry.namespace or "").lower()
        if namespace and namespace in lower_query:
            namespace_bonus += 2.0
        device_bonus = 0.0
        for alias in (entry.device_name, *entry.device_aliases):
            alias_l = alias.lower()
            if alias_l and alias_l in lower_query:
                device_bonus += 4.0

        scored.append((bm25 + name_bonus + namespace_bonus + device_bonus, entry))

    scored.sort(key=lambda item: (-item[0], item[1].name))
    return scored


def _score_edge_tools(
    query: str,
    entries: list[ToolCatalogEntry],
    *,
    embed_model: str | None,
) -> list[tuple[float, ToolCatalogEntry]]:
    embedded = _score_edge_tools_with_embeddings(query, entries, embed_model=embed_model)
    if embedded is not None:
        return embedded
    return _score_edge_tools_lexical(query, entries)


def _dedupe_entries(entries: list[ToolCatalogEntry]) -> list[ToolCatalogEntry]:
    seen: set[str] = set()
    out: list[ToolCatalogEntry] = []
    for entry in entries:
        if entry.name in seen:
            continue
        seen.add(entry.name)
        out.append(entry)
    return out


class ToolCatalog:
    """Build a request-scoped catalog from the active registries."""

    def __init__(self, *, identity=None, disabled_tools: set[str], edge_registry: dict[str, dict]):
        self.identity = identity or get_current_identity()
        self.disabled_tools = disabled_tools
        self.edge_registry = edge_registry

    def core_tools(self) -> list[ToolCatalogEntry]:
        out: list[ToolCatalogEntry] = []
        for name, tool_data in TOOL_REGISTRY.items():
            if name in self.disabled_tools:
                continue
            schema = tool_data.get("schema") or {}
            out.append(
                ToolCatalogEntry(
                    name=_tool_name(schema) or name,
                    kind="core",
                    schema=schema,
                    description=_tool_description(schema),
                    parameters_text=_parameter_text(schema),
                    namespace="core",
                    enabled=True,
                )
            )
        return out

    def edge_tools(self) -> list[ToolCatalogEntry]:
        allowed = get_edge_scope().filter_edge_tool_schemas(
            self.identity,
            self.edge_registry,
            self.disabled_tools,
        )
        allowed_names = {_tool_name(schema) for schema in allowed if _tool_name(schema)}
        if not allowed_names:
            return []

        out: list[ToolCatalogEntry] = []
        for edge_key, edge_tools in self.edge_registry.items():
            for name, entry in edge_tools.items():
                if name in self.disabled_tools or name not in allowed_names:
                    continue
                schema = entry.get("schema") or {}
                tool_name = _tool_name(schema) or name
                device_name = _edge_display_name(edge_key)
                aliases = _edge_aliases(edge_key, tool_name)
                out.append(
                    ToolCatalogEntry(
                        name=tool_name,
                        kind="edge",
                        schema=schema,
                        description=_tool_description(schema),
                        parameters_text=_parameter_text(schema),
                        namespace=f"device:{device_name}",
                        edge_key=edge_key,
                        device_name=device_name,
                        device_aliases=aliases,
                        enabled=True,
                        always_include=bool(entry.get("always_include")),
                    )
                )
        return out


def select_tool_schemas(
    *,
    identity=None,
    query: str | None,
    session_id: str,
    disabled_tools: set[str],
    edge_registry: dict[str, dict],
    force_edge_tool_names: set[str] | None = None,
) -> ToolRoutingDecision:
    """Return core tools plus the most relevant edge tools for one turn."""

    started = time.perf_counter()
    cfg = load_model_config()
    catalog = ToolCatalog(identity=identity, disabled_tools=disabled_tools, edge_registry=edge_registry)
    core_entries = catalog.core_tools()
    edge_entries = catalog.edge_tools()

    dynamic_enabled = bool(cfg.edge_tools_enable_dynamic_routing)
    edge_limit = max(0, min(200, int(cfg.edge_tools_retrieval_limit)))
    forced_names = set(force_edge_tool_names or set())
    always_entries = [entry for entry in edge_entries if entry.always_include]
    always_names = {entry.name for entry in always_entries}

    if not dynamic_enabled:
        selected_edge = edge_entries
    elif edge_limit <= 0:
        selected_edge = always_entries + [
            entry for entry in edge_entries if entry.name in forced_names and entry.name not in always_names
        ]
    elif len(edge_entries) <= edge_limit:
        selected_edge = edge_entries
    else:
        forced = [entry for entry in edge_entries if entry.name in forced_names and entry.name not in always_names]
        base = _dedupe_entries(always_entries + forced)
        base_name_set = {entry.name for entry in base}
        remaining = [entry for entry in edge_entries if entry.name not in base_name_set]
        scored = _score_edge_tools(query or "", remaining, embed_model=cfg.embedding_model)
        selected_edge = base + [entry for _, entry in scored[: max(0, edge_limit - len(base))]]
        selected_edge = _dedupe_entries(selected_edge)

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    decision = ToolRoutingDecision(
        tools=[model_visible_tool_schema(entry.schema) for entry in core_entries + selected_edge],
        core_tools=core_entries,
        selected_edge_tools=selected_edge,
        total_edge_tools=len(edge_entries),
        dynamic_routing_enabled=dynamic_enabled,
        elapsed_ms=elapsed_ms,
    )
    record_tool_routing_trace(session_id=session_id, query=query, decision=decision)
    return decision


def record_tool_routing_trace(
    *,
    session_id: str,
    query: str | None,
    decision: ToolRoutingDecision,
) -> None:
    """Keep an in-memory routing trace for debugging and evaluation."""

    rec = {
        "id": str(uuid.uuid4()),
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "query_preview": (query or "")[:500],
        "core_count": len(decision.core_tools),
        "selected_edge_count": len(decision.selected_edge_tools),
        "total_edge_count": decision.total_edge_tools,
        "dynamic_routing_enabled": decision.dynamic_routing_enabled,
        "elapsed_ms": decision.elapsed_ms,
        "selected_edge_tools": [entry.name for entry in decision.selected_edge_tools],
    }
    with _ROUTING_TRACE_LOCK:
        _ROUTING_TRACES.appendleft(rec)
    if decision.total_edge_tools > len(decision.selected_edge_tools):
        logger.debug(
            "Tool routing selected %s/%s edge tools for session %s in %sms",
            len(decision.selected_edge_tools),
            decision.total_edge_tools,
            session_id,
            decision.elapsed_ms,
        )


def list_tool_routing_traces(*, session_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    limit = max(1, min(_MAX_ROUTING_TRACES, limit))
    with _ROUTING_TRACE_LOCK:
        items = list(_ROUTING_TRACES)
    out: list[dict[str, Any]] = []
    for rec in items:
        if session_id and rec.get("session_id") != session_id:
            continue
        out.append(dict(rec))
        if len(out) >= limit:
            break
    return out


def record_tool_routing_usage(
    *,
    session_id: str,
    prompt_tokens: int,
    completion_tokens: int,
    model: str,
) -> None:
    """Record token usage alongside routing traces for later evaluation."""

    rec = {
        "id": str(uuid.uuid4()),
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": "usage",
        "session_id": session_id,
        "prompt_tokens": int(prompt_tokens or 0),
        "completion_tokens": int(completion_tokens or 0),
        "model": model or "",
    }
    with _ROUTING_TRACE_LOCK:
        _ROUTING_TRACES.appendleft(rec)


def clear_tool_routing_traces() -> None:
    with _ROUTING_TRACE_LOCK:
        _ROUTING_TRACES.clear()
