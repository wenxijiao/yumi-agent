"""Contract tests for /config/chat-debug."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from kumi.core.api.routers.chat import get_chat_debug_endpoint, put_chat_debug_endpoint
from kumi.core.api.schemas import ChatDebugRequest


def test_put_chat_debug_toggle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("kumi.core.api.chat_debug_trace.debug_dir", lambda: str(tmp_path))
    from kumi.core.platform.plugins import LOCAL_IDENTITY

    async def _run():
        up = await put_chat_debug_endpoint(LOCAL_IDENTITY, ChatDebugRequest(session_id="default", enabled=True))
        st = await get_chat_debug_endpoint(LOCAL_IDENTITY, session_id="default")
        down = await put_chat_debug_endpoint(LOCAL_IDENTITY, ChatDebugRequest(session_id="default", enabled=False))
        st2 = await get_chat_debug_endpoint(LOCAL_IDENTITY, session_id="default")
        return up, st, down, st2

    up, st, down, st2 = asyncio.run(_run())
    assert up["enabled"] is True
    assert up["trace_path"]
    assert Path(up["trace_path"]).exists()

    assert st["enabled"] is True
    assert st["trace_path"]

    assert down["enabled"] is False
    assert down["trace_path"]

    assert st2["enabled"] is False


def test_put_chat_debug_end_when_inactive() -> None:
    from kumi.core.platform.plugins import LOCAL_IDENTITY

    async def _run():
        return await put_chat_debug_endpoint(LOCAL_IDENTITY, ChatDebugRequest(session_id="default", enabled=False))

    down = asyncio.run(_run())
    assert down["enabled"] is False
    assert down["trace_path"] == ""
