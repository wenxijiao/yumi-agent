"""Tool confirm postback resolves pending future."""

import asyncio

from yumi.line.flex_builders import format_postback, parse_postback
from yumi.line.pending import PENDING_TOOL_CONFIRM


def test_tool_confirm_postback_sets_future():
    async def _run():
        short_id = "abcd1234"
        fut: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        PENDING_TOOL_CONFIRM[short_id] = fut
        data = format_postback("tool_confirm", short_id, "allow")
        assert parse_postback(data) == ("tool_confirm", short_id, "allow")
        verb, sid, arg = parse_postback(data)  # type: ignore[misc]
        assert verb == "tool_confirm"
        f2 = PENDING_TOOL_CONFIRM.get(sid)
        assert f2 is fut
        f2.set_result(arg)
        assert await asyncio.wait_for(fut, timeout=1.0) == "allow"
        PENDING_TOOL_CONFIRM.pop(short_id, None)

    asyncio.run(_run())
