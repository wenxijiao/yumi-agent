"""FastAPI dependencies for Yumi API routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from yumi.core.platform.plugins import Identity, get_current_identity
from yumi.core.platform.runtime import RuntimeState, get_default_runtime


def get_runtime(request: Request | None = None) -> RuntimeState:
    """Return the runtime attached to a FastAPI app, falling back to the default."""
    if request is not None:
        runtime = getattr(request.app.state, "runtime", None)
        if runtime is not None:
            return runtime
    return get_default_runtime()


def current_identity_dependency() -> Identity:
    # By design this returns the single local identity: yumi-agent is a personal
    # single-user agent meant to run on your own machine (default bind is
    # loopback — see SECURITY.md). There is no login because there is one user.
    # The identity is resolved through a plugin port, so the same routes can be
    # extended for other deployment models without changing this code.
    return get_current_identity()


CurrentIdentity = Annotated[Identity, Depends(current_identity_dependency)]
