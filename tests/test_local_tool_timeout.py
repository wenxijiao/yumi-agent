"""A blocking sync tool must run off the event loop so the dispatch timeout works."""

import asyncio
import time

import pytest
from yumi.core.platform.tools.tool import TOOL_REGISTRY, execute_registered_tool


def test_sync_blocking_tool_can_time_out():
    # A synchronous tool that blocks (like web_search's urlopen). If it ran
    # inline on the event loop, asyncio.wait_for could not fire until it
    # returned; running it in a worker thread lets the timeout work.
    def slow():
        time.sleep(1.0)
        return "done"

    TOOL_REGISTRY["__test_slow_tool"] = {"callable": slow}
    try:

        async def main():
            return await asyncio.wait_for(execute_registered_tool("__test_slow_tool", {}), timeout=0.2)

        with pytest.raises(asyncio.TimeoutError):
            asyncio.run(main())
    finally:
        TOOL_REGISTRY.pop("__test_slow_tool", None)


def test_async_tool_still_awaited():
    async def fast():
        await asyncio.sleep(0)
        return "async-ok"

    TOOL_REGISTRY["__test_async_tool"] = {"callable": fast}
    try:
        assert asyncio.run(execute_registered_tool("__test_async_tool", {})) == "async-ok"
    finally:
        TOOL_REGISTRY.pop("__test_async_tool", None)
