"""Nonblocking Enter-to-wake, without a stdin thread surviving Ctrl+C."""

from __future__ import annotations

import asyncio
import contextlib
import sys


class EnterToWake:
    def __init__(self, callback):
        self.callback = callback
        self._loop = None
        self._fd = None
        self._task = None

    async def __aenter__(self):
        if not sys.stdin.isatty():
            return self
        self._loop = asyncio.get_running_loop()
        if sys.platform == "win32":
            self._task = asyncio.create_task(self._poll_windows())
        else:
            try:
                self._fd = sys.stdin.fileno()
                self._loop.add_reader(self._fd, self._read_line)
            except (OSError, ValueError, NotImplementedError):
                self._fd = None
        return self

    def _read_line(self):
        line = sys.stdin.readline()
        if not line:
            if self._fd is not None:
                self._loop.remove_reader(self._fd)
                self._fd = None
        elif not line.strip():
            self.callback()

    async def _poll_windows(self):
        import msvcrt

        while True:
            if msvcrt.kbhit() and msvcrt.getwch() in {"\r", "\n"}:
                self.callback()
            await asyncio.sleep(0.05)

    async def __aexit__(self, *_):
        if self._fd is not None:
            self._loop.remove_reader(self._fd)
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
