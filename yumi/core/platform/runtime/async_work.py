"""Move blocking work off the event loop without outliving its privacy lease."""

import asyncio
from functools import partial


async def run_blocking(function, *args, **kwargs):
    task = asyncio.create_task(asyncio.to_thread(partial(function, *args, **kwargs)))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        # Threads cannot be cancelled. Finish cleanup before the caller releases
        # its account lease/session lock, then propagate cancellation.
        try:
            await task
        except Exception:
            pass
        raise
