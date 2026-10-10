import asyncio
import os
from types import SimpleNamespace

from yumi.voice.terminal import EnterToWake


def test_enter_handler_is_removed_before_pause_or_shutdown(monkeypatch):
    async def run():
        read, write = os.pipe()
        called = asyncio.Event()
        with os.fdopen(read) as stdin, os.fdopen(write, "w") as writer:
            fake = SimpleNamespace(isatty=lambda: True, fileno=stdin.fileno, readline=stdin.readline)
            monkeypatch.setattr("yumi.voice.terminal.sys.stdin", fake)
            async with EnterToWake(called.set):
                writer.write("\n")
                writer.flush()
                await asyncio.wait_for(called.wait(), timeout=1)
            assert asyncio.get_running_loop().remove_reader(read) is False

    asyncio.run(run())
