"""Shared mutable state and helpers for the Kumi core API.

The module-level UPPERCASE names (``ACTIVE_CONNECTIONS``, ``DISABLED_TOOLS``,
``TIMER_TASKS`` …) and lowercase singletons (``bot``, ``proactive_service``,
``RELAY_CLIENT``, ``server_draining``) are read-through views of
:data:`_runtime`. Attribute access goes via PEP 562 ``__getattr__`` so the
*runtime instance* is the single source of truth — swapping ``_runtime`` (e.g.
in enterprise tests) is one assignment and every reader sees it immediately.
"""

import asyncio
from typing import TYPE_CHECKING, Any

from kumi.core.memories.memory import Memory
from kumi.core.platform.runtime import RuntimeState, get_default_runtime
from kumi.core.platform.runtime.tool_catalog import model_visible_tool_schema as _model_visible_tool_schema
from kumi.logging_config import get_logger

if TYPE_CHECKING:
    # Static type stubs for the names resolved through ``__getattr__``. These
    # are never evaluated at runtime; PEP 562 ``__getattr__`` below is what
    # actually returns the live values from the active ``_runtime``.
    ACTIVE_CONNECTIONS: dict
    EDGE_TOOLS_REGISTRY: dict
    PENDING_TOOL_CALLS: dict
    PENDING_EDGE_OPS: dict
    RELAY_EDGE_PEERS: dict
    DISABLED_TOOLS: set[str]
    CONFIRMATION_TOOLS: set[str]
    ALWAYS_ALLOWED_TOOLS: set[str]
    PENDING_CONFIRMATIONS: dict
    SESSION_LOCKS: dict
    TIMER_TASKS: dict
    TIMER_SUBSCRIBERS: list[tuple[Any, str | None]]
    bot: Any
    proactive_service: Any
    RELAY_CLIENT: Any
    server_draining: bool


logger = get_logger(__name__)

_runtime: RuntimeState = get_default_runtime()

# Names resolved through ``__getattr__`` against ``_runtime``. Listed for
# docs/reflection and to keep grep-ability for refactoring tools.
_RUNTIME_ATTR_MAP: dict[str, tuple[str, ...]] = {
    "ACTIVE_CONNECTIONS": ("edge_registry", "active_connections"),
    "EDGE_TOOLS_REGISTRY": ("edge_registry", "tools"),
    "PENDING_TOOL_CALLS": ("edge_registry", "pending_tool_calls"),
    "PENDING_EDGE_OPS": ("edge_registry", "pending_file_ops"),
    "RELAY_EDGE_PEERS": ("edge_registry", "relay_edge_peers"),
    "DISABLED_TOOLS": ("tool_policy", "disabled_tools"),
    "CONFIRMATION_TOOLS": ("tool_policy", "confirmation_tools"),
    "ALWAYS_ALLOWED_TOOLS": ("tool_policy", "always_allowed_tools"),
    "PENDING_CONFIRMATIONS": ("tool_policy", "pending_confirmations"),
    "SESSION_LOCKS": ("session_locks", "locks"),
    "TIMER_TASKS": ("timer_registry", "tasks"),
    "TIMER_SUBSCRIBERS": ("timer_registry", "subscribers"),
    "bot": ("bot",),
    "proactive_service": ("proactive_service",),
    "RELAY_CLIENT": ("relay_client",),
    "server_draining": ("server_draining",),
}


def __getattr__(name: str) -> Any:
    path = _RUNTIME_ATTR_MAP.get(name)
    if path is None:
        raise AttributeError(f"module 'kumi.core.api.state' has no attribute {name!r}")
    obj: Any = _runtime
    for part in path:
        obj = getattr(obj, part)
    return obj


# ── bot accessor ──


def get_bot():
    """Return the active KumiBot instance or raise RuntimeError."""
    if _runtime.bot is None:
        raise RuntimeError(
            "Kumi server has no configured chat model. Run `kumi --setup` or start with `kumi --server`."
        )
    return _runtime.bot


def set_runtime(runtime: RuntimeState) -> None:
    """Swap the runtime backing this facade."""
    global _runtime
    _runtime = runtime


def get_runtime() -> RuntimeState:
    """Return the runtime currently backing the facade."""
    return _runtime


def set_bot(active_bot) -> None:
    _runtime.bot = active_bot


def set_proactive_service(service) -> None:
    _runtime.proactive_service = service


def set_relay_client(client) -> None:
    _runtime.relay_client = client


def set_server_draining(value: bool) -> None:
    _runtime.server_draining = value


# ── memory store ──

_memory_store: Memory | None = None


def get_memory_store() -> Memory:
    if _runtime.memory_store is None:
        _runtime.memory_store = Memory(session_id="default")
    return _runtime.memory_store


def get_memory_store_for_identity(identity) -> Memory:
    """Return the Memory store for *identity* via the plugin layer."""
    from kumi.core.platform.plugins import get_memory_factory

    return get_memory_factory().get_for_identity(identity)


# ── session lock ──


def get_session_lock(session_id: str) -> asyncio.Lock:
    return _runtime.session_locks.get(session_id)


def prune_session_locks_if_needed(max_entries: int = 5000) -> None:
    """Best-effort trim when too many session locks accumulate (unlocked entries only)."""
    _runtime.session_locks.prune_if_needed(max_entries)


# ── tool schema helpers ──


def get_all_tool_schemas(identity=None):
    return _runtime.tool_catalog.all_tool_schemas(identity)


def model_visible_tool_schema(schema: dict) -> dict:
    """Compatibility wrapper for provider-visible tool schemas."""
    return _model_visible_tool_schema(schema)


def get_tool_timeout(prefixed_name: str) -> int:
    from kumi.core.services.chat_turn import TOOL_CALL_TIMEOUT_DEFAULT

    return _runtime.tool_catalog.tool_timeout(prefixed_name, TOOL_CALL_TIMEOUT_DEFAULT)


# ── edge tool name splitting (re-exported from runtime.edge_naming) ──

from kumi.core.platform.runtime.edge_naming import (  # noqa: E402, F401
    edge_connection_key,
    edge_tool_key_prefix,
    edge_tool_register_prefix,
    gemini_safe_edge_segment,
    parse_edge_connection_key,
    split_edge_prefixed_tool,
)
from kumi.core.platform.runtime.edge_naming import (  # noqa: E402
    resolve_edge_for_prefixed_tool_name as _resolve_edge_for_prefixed_tool_name,
)


def resolve_edge_for_prefixed_tool_name(prefixed_name: str) -> str | None:
    """Compat wrapper that defaults to the live runtime edge registry."""
    return _resolve_edge_for_prefixed_tool_name(prefixed_name, _runtime.edge_registry)


# ── stream event helper ──


def stream_event(event_type: str, **payload) -> str:
    import json

    return json.dumps({"type": event_type, **payload}) + "\n"
