"""Runtime registry for connected edge peers and their tools."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EdgeRegistry:
    """Owns all mutable edge connection state for one Yumi runtime."""

    active_connections: dict[str, Any] = field(default_factory=dict)
    tools: dict[str, dict] = field(default_factory=dict)
    pending_tool_calls: dict[str, dict[str, Any]] = field(default_factory=dict)
    pending_file_ops: dict[str, dict[str, Any]] = field(default_factory=dict)

    def cancel_pending_for_peer(self, connection_key: str, peer: Any, exc: BaseException) -> None:
        """Fail all pending edge operations owned by a disconnected peer."""
        for call_id, pending in list(self.pending_tool_calls.items()):
            if pending.get("edge_name") != connection_key or pending.get("peer") is not peer:
                continue
            future: asyncio.Future | None = pending.get("future")
            if future is not None and not future.done():
                future.set_exception(exc)
            self.pending_tool_calls.pop(call_id, None)

        for op_id, pending in list(self.pending_file_ops.items()):
            if pending.get("edge_name") != connection_key or pending.get("peer") is not peer:
                continue
            future: asyncio.Future | None = pending.get("future")
            if future is not None and not future.done():
                future.set_exception(exc)
            self.pending_file_ops.pop(op_id, None)
