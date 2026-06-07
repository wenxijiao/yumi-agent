"""Runtime construction helpers."""

from __future__ import annotations

from kumi.core.platform.runtime.state import RuntimeState


def build_runtime() -> RuntimeState:
    """Create an isolated Kumi runtime context."""
    return RuntimeState()
