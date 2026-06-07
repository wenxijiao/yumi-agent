"""Timer event streaming routes."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from kumi.core.api.dependencies import CurrentIdentity
from kumi.core.api.state import TIMER_SUBSCRIBERS
from kumi.tools.timer_tools import cancel_timer_for_owner, timer_entries_for_owner

router = APIRouter()


@router.get("/timer-events")
async def timer_events_endpoint(identity: CurrentIdentity):  # noqa: ARG001
    queue: asyncio.Queue = asyncio.Queue(maxsize=64)
    sub = (queue, None)
    TIMER_SUBSCRIBERS.append(sub)

    async def event_stream():
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=30)
                    yield json.dumps(payload, ensure_ascii=False) + "\n"
                except asyncio.TimeoutError:
                    yield json.dumps({"type": "heartbeat"}) + "\n"
        except asyncio.CancelledError:
            pass
        finally:
            try:
                TIMER_SUBSCRIBERS.remove(sub)
            except ValueError:
                pass

    return StreamingResponse(event_stream(), media_type="application/x-ndjson")


@router.get("/timers")
async def list_timers_endpoint(identity: CurrentIdentity):
    return {"timers": timer_entries_for_owner(identity.user_id)}


@router.delete("/timers/{timer_id}")
async def cancel_timer_endpoint(timer_id: str, identity: CurrentIdentity):
    ok, message, timer = cancel_timer_for_owner(timer_id, identity.user_id)
    return {
        "status": "success" if ok else "error",
        "message": message,
        "timer": timer,
    }
