"""Timer scheduling helpers.

A scheduled timer is just an ``asyncio.Task`` that sleeps for ``delay``
seconds, then drives a follow-up chat turn through ``generate_chat_events``
and fans the resulting events out to LINE/Telegram and any subscribers
listening on ``/timer-events``. Recurring timers reschedule themselves.
"""

from __future__ import annotations

import asyncio
import logging

from kumi.core.features.proactive.timer_tools import calc_next_recurring_delay, scheduler
from kumi.core.platform.http.task_logging import log_task_exc_on_done
from kumi.core.platform.runtime.accessors import TIMER_SUBSCRIBERS, TIMER_TASKS

logger = logging.getLogger(__name__)


async def _timer_fire(timer_id: str, delay: int, description: str, session_id: str):
    logger.info(
        "Timer sleeping %ss then firing (timer_id=%s session_id=%s desc=%r)",
        delay,
        timer_id,
        session_id,
        description[:80],
    )
    await asyncio.sleep(delay)

    logger.info("Timer fired (timer_id=%s session_id=%s)", timer_id, session_id)

    schedule = scheduler.active_timers.get(timer_id)
    recurring = schedule.get("recurring", False) if schedule else False

    if not recurring:
        scheduler.active_timers.pop(timer_id, None)
    TIMER_TASKS.pop(timer_id, None)

    from kumi.core.features.chat.pipeline import generate_chat_events

    prompt = (
        f"[Timer expired — scheduled action]\n"
        f"Planned task: {description}\n"
        f"The wait is over; this is that follow-up turn. Complete the task now: reply to the user, "
        f"or call one of the currently available tools if the task needs fresh data or an external action. "
        f"Do not schedule another delay (no new timer for something you can say or do immediately). "
        f"Answer in the same language as the user."
    )
    collected: list[dict] = []
    try:
        async for event in generate_chat_events(prompt, session_id, timer_callback=True):
            collected.append(event)
    except Exception as exc:
        collected.append({"type": "error", "content": str(exc)})

    from kumi.line.notify import send_timer_result_to_line
    from kumi.telegram.notify import send_timer_result_to_telegram

    await send_timer_result_to_telegram(session_id, description, collected)
    await send_timer_result_to_line(session_id, description, collected)

    payload = {
        "timer_id": timer_id,
        "description": description,
        "session_id": session_id,
        "events": collected,
    }
    from kumi.core.platform.plugins import get_session_scope

    owner = get_session_scope().owner_user_from_session_id(session_id)
    for sub in list(TIMER_SUBSCRIBERS):
        if isinstance(sub, tuple):
            q, subscriber_user = sub
        else:
            q, subscriber_user = sub, None
        if subscriber_user is not None and subscriber_user != owner:
            continue
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass

    if recurring and schedule:
        next_delay = calc_next_recurring_delay(schedule)
        scheduler._save_schedules()
        schedule_timer(timer_id, next_delay, description, session_id)


def schedule_timer(timer_id: str, delay: int, description: str, session_id: str) -> None:
    logger.info(
        "Timer scheduled: timer_id=%s delay=%ss session_id=%s",
        timer_id,
        delay,
        session_id,
    )
    loop = asyncio.get_running_loop()
    task = loop.create_task(_timer_fire(timer_id, delay, description, session_id))
    log_task_exc_on_done(task, f"timer_fire timer_id={timer_id!r}")
    TIMER_TASKS[timer_id] = task


def cancel_timer(timer_id: str) -> None:
    task = TIMER_TASKS.pop(timer_id, None)
    if task and not task.done():
        task.cancel()
