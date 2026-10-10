import asyncio
import contextlib
import json

import httpx
import pytest
from yumi.voice.media_wait import wait_for_media


def test_transitional_pause_and_unknown_do_not_end_media(monkeypatch):
    from yumi.voice import media_wait

    async def run():
        states = iter(["inactive", "playing", "inactive", "unknown", "ended", "ended"])
        calls = []
        clock = iter([0, 20, 21, 22])
        # Patch only this module's clock, not asyncio's global monotonic clock.
        monkeypatch.setattr(media_wait, "time", type("Clock", (), {"monotonic": staticmethod(lambda: next(clock))}))

        def handler(request):
            assert request.url.path == "/assistant/voice/playback"
            assert json.loads(request.content) == {"turn_id": "turn"}
            state = next(states)
            calls.append(state)
            return httpx.Response(200, json={"state": state})

        async with httpx.AsyncClient(base_url="https://test", transport=httpx.MockTransport(handler)) as client:
            assert await wait_for_media(client, "turn", interval=0, startup_grace=10)
        assert len(calls) == 6

    asyncio.run(run())


def test_enter_cancels_slow_status_request_without_opening_audio(monkeypatch):
    from yumi.voice import media_wait

    async def run():
        entered, cancelled = asyncio.Event(), asyncio.Event()

        @contextlib.asynccontextmanager
        async def keyboard(callback):
            async def press():
                await entered.wait()
                callback()

            task = asyncio.create_task(press())
            try:
                yield
            finally:
                await task

        async def handler(request):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        monkeypatch.setattr(media_wait, "EnterToWake", keyboard)
        async with httpx.AsyncClient(base_url="https://test", transport=httpx.MockTransport(handler)) as client:
            assert await asyncio.wait_for(wait_for_media(client, "turn"), 1)
        assert cancelled.is_set()

    asyncio.run(run())


@pytest.mark.parametrize("status", [401, 403, 404, 410])
def test_inaccessible_monitor_requires_manual_recovery(status):
    async def run():
        async with httpx.AsyncClient(
            base_url="https://test", transport=httpx.MockTransport(lambda _: httpx.Response(status))
        ) as client:
            assert not await wait_for_media(client, "turn")

    asyncio.run(run())
