"""Warm reusable tool vectors after registration, away from chat requests."""

import asyncio

from yumi.logging_config import get_logger

logger = get_logger(__name__)
_TASKS: set[asyncio.Task] = set()
_PENDING: dict[str | None, tuple[dict, str]] = {}


def schedule_tool_index(connection_key: str | None, registry: dict) -> None:
    from yumi.core.platform.tools.routing import get_embed_provider, load_model_config

    if get_embed_provider() is None:
        return
    model = load_model_config().embedding_model
    if not model:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    # Coalesce updates per device but never drop a device just because other
    # registrations are warming. A single worker bounds remote concurrency.
    _PENDING[connection_key] = (dict(registry), model)
    if any(not task.done() for task in _TASKS):
        return

    async def run():
        while _PENDING:
            key = next(iter(_PENDING))
            snapshot, embed_model = _PENDING.pop(key)
            try:
                await asyncio.to_thread(_warm, key, snapshot, embed_model)
            except Exception:
                logger.debug("Tool index warm-up skipped", exc_info=True)

    task = loop.create_task(run(), name="yumi-tool-index")
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)


def _warm(connection_key: str | None, registry: dict, model: str) -> None:
    from yumi.core.platform.tools.routing import (
        ToolCatalogEntry,
        _cached_embedding,
        _edge_aliases,
        _edge_display_name,
        _parameter_text,
        _tool_description,
    )

    device = _edge_display_name(connection_key) if connection_key is not None else ""
    for name, raw in registry.items():
        schema = raw.get("schema") or {}
        entry = ToolCatalogEntry(
            name=name,
            kind="edge" if connection_key is not None else "core",
            schema=schema,
            description=_tool_description(schema),
            parameters_text=_parameter_text(schema),
            namespace=f"device:{device}" if connection_key is not None else "core",
            edge_key=connection_key,
            device_name=device,
            device_aliases=_edge_aliases(connection_key, name) if connection_key is not None else (),
        )
        # Cache only metadata vectors. Search still builds a fresh, scoped catalog.
        _cached_embedding(model, entry.search_text, persistent=True)
        if entry.device_text:
            _cached_embedding(model, entry.device_text, persistent=True)
