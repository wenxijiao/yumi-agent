"""Runtime construction helpers."""

from __future__ import annotations

from yumi.core.platform.runtime.state import RuntimeState


def build_runtime() -> RuntimeState:
    """Create an isolated Yumi runtime context."""
    return RuntimeState()
