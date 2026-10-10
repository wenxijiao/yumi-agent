"""One-shot, account-bound speaker readiness before a music side effect.

Like chat cancellation, this rendezvous is local to the API worker. It is not
tool approval: only already-authorized invocations reach it. Missing, negative,
or late acknowledgements never start playback.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from uuid import uuid4

from fastapi import HTTPException
from yumi.core.platform.runtime.assistant_context import message_media

PREPARE_TIMEOUT = 8.0
_pending: dict[tuple[str, str], asyncio.Future] = {}


def needs_preparation(invocations) -> bool:
    return bool((message_media.get() or {}).get("prepare_media_output")) and any(
        inv.kind == "edge"
        and inv.original_tool_name in {"music_play", "music_play_request"}
        and not inv.reply_on_success
        for inv in invocations
    )


@contextmanager
def preparation(owner: str):
    preparation_id = uuid4().hex
    future = asyncio.get_running_loop().create_future()
    key = (owner, preparation_id)
    _pending[key] = future
    try:
        yield preparation_id, future
    finally:
        _pending.pop(key, None)
        if not future.done():
            future.cancel()


def acknowledge(owner: str, preparation_id: str, ready: bool) -> None:
    future = _pending.get((owner, preparation_id))
    if future is None or future.done():
        raise HTTPException(404, "Speaker preparation is no longer pending.")
    future.set_result(ready)


async def wait_until_ready(future: asyncio.Future) -> bool:
    try:
        return await asyncio.wait_for(future, timeout=PREPARE_TIMEOUT) is True
    except asyncio.TimeoutError:
        return False
