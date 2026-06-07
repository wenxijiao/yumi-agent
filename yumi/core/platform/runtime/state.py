"""Explicit runtime context for a Yumi application instance."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from yumi.core.platform.runtime.edge_registry import EdgeRegistry
from yumi.core.platform.runtime.session_locks import SessionLockRegistry
from yumi.core.platform.runtime.timer_registry import TimerRegistry
from yumi.core.platform.runtime.tool_catalog import ToolCatalog
from yumi.core.platform.runtime.tool_policy import ToolPolicy


@dataclass
class RuntimeState:
    """All mutable application state that used to live in ``api.state``."""

    bot: Any = None
    proactive_service: Any = None
    relay_client: Any = None
    server_draining: bool = False
    edge_registry: EdgeRegistry = field(default_factory=EdgeRegistry)
    session_locks: SessionLockRegistry = field(default_factory=SessionLockRegistry)
    timer_registry: TimerRegistry = field(default_factory=TimerRegistry)
    tool_policy: ToolPolicy = field(default_factory=ToolPolicy)
    memory_store: Any = None
    tool_catalog: ToolCatalog = field(init=False)

    def __post_init__(self) -> None:
        self.tool_catalog = ToolCatalog(self)


_DEFAULT_RUNTIME = RuntimeState()


def get_default_runtime() -> RuntimeState:
    """Return the process default runtime used by legacy module-level APIs."""
    return _DEFAULT_RUNTIME
