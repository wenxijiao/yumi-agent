"""Account-scoped cancellation for a single client request (one server worker).

A short-lived tombstone also covers cancellation arriving before the chat body.
Already executed tool side effects cannot be rolled back by cancellation.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict

from fastapi import HTTPException

_tasks: dict[tuple[str, str], asyncio.Task] = {}
_closed: OrderedDict[tuple[str, str], float] = OrderedDict()


def _prune() -> None:
    now = time.monotonic()
    while _closed and (next(iter(_closed.values())) < now or len(_closed) > 4096):
        _closed.popitem(last=False)


def _close(key: tuple[str, str]) -> None:
    _closed[key] = time.monotonic() + 300
    _closed.move_to_end(key)
    _prune()


def register(owner: str, request_id: str) -> bool:
    _prune()
    key = (owner, request_id)
    if key in _tasks:
        raise HTTPException(409, "Client request is already running.")
    if key in _closed:
        return False
    _tasks[key] = asyncio.current_task()
    return True


def finish(owner: str, request_id: str) -> None:
    key = (owner, request_id)
    _tasks.pop(key, None)
    _close(key)


async def cancel(owner: str, request_id: str) -> bool:
    key = (owner, request_id)
    _close(key)
    task = _tasks.get(key)
    if task is None or task.done():
        return True
    task.cancel()
    done, _ = await asyncio.wait([task], timeout=3)
    return bool(done)
