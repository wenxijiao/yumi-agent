"""Execute a tool on a connected edge peer over WebSocket.

Encapsulates the full RPC: register a future under ``call_id`` so the
incoming ``tool_result`` message can resolve it; send ``tool_call`` to the
peer; await with a per-tool timeout; on cancel/timeout/disconnect, send a
``cancel`` upstream and clean up the pending entry.
"""

from __future__ import annotations

import asyncio
import uuid

from yumi.core.platform.dispatch.context import ToolInvocation, ToolResult
from yumi.core.platform.runtime import RuntimeState


class EdgeToolExecutor:
    """Runs invocations whose ``kind == "edge"``."""

    def __init__(self, runtime: RuntimeState, *, default_timeout: int) -> None:
        self.runtime = runtime
        self.default_timeout = default_timeout

    def _timeout_for(self, prefixed_name: str) -> int:
        return self.runtime.tool_catalog.tool_timeout(prefixed_name, self.default_timeout)

    async def run(self, inv: ToolInvocation) -> ToolResult:
        assert inv.peer is not None, "edge invocation must carry its peer"
        assert inv.target_edge is not None, "edge invocation must carry target_edge"
        assert inv.original_tool_name is not None, "edge invocation must carry original_tool_name"

        call_id = str(uuid.uuid4())
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        pending = self.runtime.edge_registry.pending_tool_calls
        pending[call_id] = {
            "future": future,
            "edge_name": inv.target_edge,
            "peer": inv.peer,
        }
        frame = {
            "type": "tool_call",
            "name": inv.original_tool_name,
            "arguments": inv.args,
            "call_id": call_id,
        }
        # Caller identity travels OUTSIDE ``arguments`` — the model only ever
        # produces arguments, so it structurally cannot set or spoof this.
        if inv.caller_user_id:
            frame["caller_user_id"] = inv.caller_user_id
        try:
            await inv.peer.send_json(frame)
            result = await asyncio.wait_for(future, timeout=self._timeout_for(inv.func_name))
            return ToolResult(
                func_name=inv.func_name,
                result=str(result),
                status="success",
                original_tool_name=inv.original_tool_name,
                target_edge=inv.target_edge,
            )
        except asyncio.TimeoutError:
            await self._send_cancel(inv, call_id)
            return ToolResult(
                func_name=inv.func_name,
                result="Error: Tool execution timed out.",
                status="error",
                original_tool_name=inv.original_tool_name,
                target_edge=inv.target_edge,
            )
        except asyncio.CancelledError:
            await self._send_cancel(inv, call_id)
            raise
        except Exception as exc:
            return ToolResult(
                func_name=inv.func_name,
                result=f"Error: Tool execution failed: {exc}",
                status="error",
                original_tool_name=inv.original_tool_name,
                target_edge=inv.target_edge,
            )
        finally:
            pending.pop(call_id, None)

    @staticmethod
    async def _send_cancel(inv: ToolInvocation, call_id: str) -> None:
        try:
            await inv.peer.send_json({"type": "cancel", "call_id": call_id})
        except Exception:
            pass
