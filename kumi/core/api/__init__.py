"""Kumi core HTTP API package.

The implementation is split into:

- ``runtime``     — explicit mutable runtime state and registries
- ``app_factory`` — FastAPI application assembly and lifespan
- ``routers``     — one module per resource group (chat, config, edge, ...)
- ``state``       — module-level facade over the default runtime
- ``schemas``     — request/response Pydantic models

``app`` and ``create_app`` are resolved lazily via PEP 562 ``__getattr__`` so
that lightweight subpackages (``state``, ``chat_debug_trace``) can be imported
without spinning up the full FastAPI app — important for breaking the
``dispatch.trace_sink → core.api → app_factory → routers.chat → services
→ dispatch`` import cycle that bites when the dispatch package is loaded
before any HTTP-facing module.
"""

from typing import TYPE_CHECKING, Any

from kumi.core.platform.runtime.accessors import stream_event

if TYPE_CHECKING:
    from fastapi import FastAPI

    app: "FastAPI"

    def create_app() -> "FastAPI": ...


__all__ = ["app", "create_app", "stream_event"]


def __getattr__(name: str) -> Any:
    if name in ("app", "create_app"):
        from kumi.core.api.app_factory import app, create_app

        return {"app": app, "create_app": create_app}[name]
    raise AttributeError(f"module 'kumi.core.api' has no attribute {name!r}")
