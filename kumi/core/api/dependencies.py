"""FastAPI dependencies for Kumi API routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from kumi.core.plugins import Identity, get_current_identity
from kumi.core.runtime import RuntimeState, get_default_runtime


def get_runtime(request: Request | None = None) -> RuntimeState:
    """Return the runtime attached to a FastAPI app, falling back to the default."""
    if request is not None:
        runtime = getattr(request.app.state, "runtime", None)
        if runtime is not None:
            return runtime
    return get_default_runtime()


def current_identity_dependency() -> Identity:
    return get_current_identity()


CurrentIdentity = Annotated[Identity, Depends(current_identity_dependency)]
