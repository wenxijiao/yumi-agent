"""Runtime registry for timer tasks and event subscribers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

TimerSubscriber = tuple[asyncio.Queue, str | None]


@dataclass
class TimerRegistry:
    """Owns scheduled timer tasks and streaming subscribers."""

    tasks: dict[str, asyncio.Task] = field(default_factory=dict)
    subscribers: list[TimerSubscriber] = field(default_factory=list)

    def add_subscriber(self, queue: asyncio.Queue, owner_user_id: str | None = None) -> TimerSubscriber:
        sub = (queue, owner_user_id)
        self.subscribers.append(sub)
        return sub

    def remove_subscriber(self, sub: TimerSubscriber) -> None:
        try:
            self.subscribers.remove(sub)
        except ValueError:
            pass
