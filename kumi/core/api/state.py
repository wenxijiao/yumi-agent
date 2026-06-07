"""Deprecated facade — runtime accessors moved to
``kumi.core.platform.runtime.accessors`` and memory-store construction to
``kumi.core.features.memory.store``.

Kept as the historical ``kumi.core.api.state`` import surface for one release
(removed in a later phase). New code should import from the canonical modules.
The PEP 562 ``__getattr__`` below delegates to the platform accessors so the
single ``_runtime`` source of truth is preserved across ``set_runtime``.
"""

from typing import Any

from kumi.core.features.memory.store import (  # noqa: F401
    get_memory_store,
    get_memory_store_for_identity,
)
from kumi.core.platform.runtime import accessors as _accessors
from kumi.core.platform.runtime.accessors import (  # noqa: F401
    edge_connection_key,
    edge_tool_key_prefix,
    edge_tool_register_prefix,
    gemini_safe_edge_segment,
    get_all_tool_schemas,
    get_bot,
    get_runtime,
    get_session_lock,
    get_tool_timeout,
    model_visible_tool_schema,
    parse_edge_connection_key,
    prune_session_locks_if_needed,
    resolve_edge_for_prefixed_tool_name,
    set_bot,
    set_proactive_service,
    set_relay_client,
    set_runtime,
    set_server_draining,
    split_edge_prefixed_tool,
    stream_event,
)


def __getattr__(name: str) -> Any:
    # Delegate runtime-backed names (ACTIVE_CONNECTIONS, TIMER_TASKS, bot, …)
    # to the platform accessors so there is a single _runtime source of truth.
    try:
        return getattr(_accessors, name)
    except AttributeError:
        raise AttributeError(f"module 'kumi.core.api.state' has no attribute {name!r}") from None
