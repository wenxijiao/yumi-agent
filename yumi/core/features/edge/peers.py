"""WebSocket peer abstractions for local edge connections.

Relay peer (``RelayEdgePeer``) lives in the enterprise package — OSS only
needs the local LAN peer wrapper.
"""

from __future__ import annotations

import asyncio

from fastapi import WebSocket


class EdgePeerDisconnected(Exception):
    pass


class LocalEdgePeer:
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket
        self._send_lock = asyncio.Lock()

    async def receive_json(self):
        return await self.websocket.receive_json()

    async def send_json(self, payload: dict):
        async with self._send_lock:
            await self.websocket.send_json(payload)

    async def close(self, code: int = 1000, reason: str = ""):
        await self.websocket.close(code=code, reason=reason)
