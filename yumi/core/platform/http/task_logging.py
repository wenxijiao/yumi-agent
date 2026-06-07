"""Helpers for fire-and-forget asyncio tasks."""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


def log_task_exc_on_done(task: asyncio.Task, what: str) -> None:
    """Log exceptions from a task that is never awaited (avoids 'never retrieved' warnings)."""

    def _done(t: asyncio.Task) -> None:
        try:
            exc = t.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            logger.error("%s: background asyncio task failed", what, exc_info=exc)

    task.add_done_callback(_done)
