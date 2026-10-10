"""Wait for verified player inactivity without opening any audio device."""

from __future__ import annotations

import asyncio
import contextlib
import time

import httpx

from yumi.voice.terminal import EnterToWake


async def wait_for_media(http, turn_id, *, interval=2, startup_grace=10) -> bool:
    """True means restart capture; False leaves explicit manual recovery.

    Two inactive samples after a startup grace period avoid briefly paused
    MusicKit snapshots during Bluetooth route changes. Unknown/offline is never
    interpreted as finished. Enter remains responsive during network requests.
    """
    manual = asyncio.Event()

    async def poll():
        started = time.monotonic()
        inactive = 0
        seen_playing = False
        warned = False
        while True:
            delay = interval
            state = "unknown"
            try:
                response = await http.post("/assistant/voice/playback", json={"turn_id": turn_id}, timeout=10)
                if response.status_code in {401, 403, 404, 410}:
                    print(
                        "Playback monitoring is unavailable. Microphone stays released; press Enter to resume.",
                        flush=True,
                    )
                    return False
                response.raise_for_status()
                state = response.json().get("state", "unknown")
            except (httpx.HTTPError, ValueError, AttributeError):
                delay = max(interval, 10)
            if state == "playing":
                seen_playing = True
            # A paused initial snapshot is not proof playback ever started.
            # An explicitly retired/empty queue can finish even a short track
            # that fell entirely between polls.
            if (
                state == "ended" or (state == "inactive" and seen_playing)
            ) and time.monotonic() - started >= startup_grace:
                inactive += 1
                if inactive >= (2 if state == "ended" else 3):
                    return True
            else:
                inactive = 0
            if state == "unknown" and not warned:
                print("Waiting for player status. Microphone stays released; press Enter to resume.", flush=True)
                warned = True
            await asyncio.sleep(delay)

    async with EnterToWake(manual.set):
        polling = asyncio.create_task(poll())
        keyboard = asyncio.create_task(manual.wait())
        try:
            done, _ = await asyncio.wait({polling, keyboard}, return_when=asyncio.FIRST_COMPLETED)
            return keyboard in done or polling.result()
        finally:
            for task in (polling, keyboard):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
