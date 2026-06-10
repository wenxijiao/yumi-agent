"""Explicit runtime context for a Yumi application instance."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from yumi.core.platform.runtime.edge_registry import EdgeRegistry
from yumi.core.platform.runtime.session_locks import SessionLockRegistry
from yumi.core.platform.runtime.timer_registry import TimerRegistry
from yumi.core.platform.runtime.tool_catalog import ToolCatalog
from yumi.core.platform.runtime.tool_policy import ToolPolicy

if TYPE_CHECKING:
    # Type-only references. These live outside ``platform`` (chatbot is the
    # composition object; the others are features), so they are imported under
    # TYPE_CHECKING to keep the platform → features rule intact at import time
    # (see tests/test_architecture_boundaries.py, which skips these blocks).
    # ``from __future__ import annotations`` makes every annotation below a
    # string, so nothing here is evaluated at runtime.
    from yumi.core.chatbot import YumiBot
    from yumi.core.features.memory.memory import Memory
    from yumi.core.features.proactive.service import ProactiveMessageService


@dataclass
class RuntimeState:
    """All mutable application state that used to live in ``api.state``."""

    bot: YumiBot | None = None
    proactive_service: ProactiveMessageService | None = None
    server_draining: bool = False
    edge_registry: EdgeRegistry = field(default_factory=EdgeRegistry)
    session_locks: SessionLockRegistry = field(default_factory=SessionLockRegistry)
    timer_registry: TimerRegistry = field(default_factory=TimerRegistry)
    tool_policy: ToolPolicy = field(default_factory=ToolPolicy)
    memory_store: Memory | None = None
    tool_catalog: ToolCatalog = field(init=False)

    def __post_init__(self) -> None:
        self.tool_catalog = ToolCatalog(self)


_DEFAULT_RUNTIME = RuntimeState()


def get_default_runtime() -> RuntimeState:
    """Return the process default runtime used by legacy module-level APIs."""
    return _DEFAULT_RUNTIME
