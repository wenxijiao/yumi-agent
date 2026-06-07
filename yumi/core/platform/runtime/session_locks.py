"""Per-session lock registry for chat turns."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass
class SessionLockRegistry:
    """Creates and prunes async locks scoped to one runtime instance."""

    locks: dict[str, asyncio.Lock] = field(default_factory=dict)

    def get(self, session_id: str) -> asyncio.Lock:
        lock = self.locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self.locks[session_id] = lock
        return lock

    def discard(self, session_id: str) -> None:
        self.locks.pop(session_id, None)

    def prune_if_needed(self, max_entries: int = 5000) -> None:
        if len(self.locks) < max_entries:
            return
        for sid, lock in list(self.locks.items()):
            if not lock.locked():
                self.locks.pop(sid, None)
