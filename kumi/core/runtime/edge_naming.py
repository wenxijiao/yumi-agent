"""Edge tool / connection naming helpers.

Pure string-keyed helpers shared by the dispatch layer, the API edge router,
and the proactive runner. They live here (under ``runtime``) so the dispatch
domain can depend on them without pulling in the API layer — which used to
force inline imports inside async methods to dodge a cycle.
"""

from __future__ import annotations

import re

from kumi.core.runtime.edge_registry import EdgeRegistry


def gemini_safe_edge_segment(edge_name: str) -> str:
    """Make a substring safe for Gemini ``function_declarations[].name``.

    Allowed: letters, digits, ``_ . : -`` (see Google GenAI INVALID_ARGUMENT on tool names).
    """
    s = (edge_name or "").strip()
    if not s:
        return "edge"
    t = re.sub(r"[^a-zA-Z0-9_.:-]+", "_", s)
    t = re.sub(r"_+", "_", t).strip("_")
    if not t:
        return "edge"
    if t[0] in "0123456789.-:":
        t = "e" + t
    return t[:80]


def edge_tool_key_prefix(edge_name: str) -> str:
    """Prefix for tools registered from an edge device, e.g. ``edge_My_Device__``."""
    return f"edge_{gemini_safe_edge_segment(edge_name)}__"


def edge_connection_key(owner_user_id: str | None, edge_name: str) -> str:
    """Registry key for an edge — the EdgeScope plugin chooses the layout."""
    from kumi.core.plugins import get_edge_scope

    return get_edge_scope().connection_key(owner_user_id, edge_name)


def edge_tool_register_prefix(owner_user_id: str | None, edge_name: str) -> str:
    """Tool name prefix for registration (per-user prefix in MT, plain in OSS)."""
    from kumi.core.plugins import get_edge_scope

    return get_edge_scope().tool_register_prefix(owner_user_id, edge_name)


def parse_edge_connection_key(connection_key: str) -> tuple[str | None, str]:
    """Split registry key into (owner_user_id or None, logical edge_name)."""
    if connection_key.startswith("u:"):
        rest = connection_key[2:]
        owner, _, edge = rest.partition("::")
        return (owner or None, edge) if edge else (None, connection_key)
    return None, connection_key


def resolve_edge_for_prefixed_tool_name(prefixed_name: str, edge_registry: EdgeRegistry | None = None) -> str | None:
    """Map a full prefixed tool name to the connection key holding it.

    Searches ``edge_registry.tools`` (defaults to the process-wide runtime).
    """
    if edge_registry is None:
        from kumi.core.runtime import get_default_runtime

        edge_registry = get_default_runtime().edge_registry
    for en, tools_map in edge_registry.tools.items():
        if prefixed_name in tools_map:
            return en
    return None


def split_edge_prefixed_tool(prefixed_name: str) -> tuple[str | None, str | None]:
    """Parse ``edge_<segment>__<original>`` into (segment, original)."""
    if not prefixed_name.startswith("edge_"):
        return None, None
    rest = prefixed_name[5:]
    if "__" not in rest:
        return None, None
    segment, _, original = rest.partition("__")
    if not segment or not original:
        return None, None
    return segment, original
