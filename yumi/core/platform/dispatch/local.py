"""Execute a registered local tool with timeout and structured error capture."""

from __future__ import annotations

import asyncio

from yumi.core.platform.dispatch.context import ToolInvocation, ToolResult
from yumi.core.platform.tools.tool import execute_registered_tool


class LocalToolExecutor:
    """Runs invocations whose ``kind == "local"``."""

    def __init__(self, *, timeout: int) -> None:
        self.timeout = timeout

    async def run(self, inv: ToolInvocation) -> ToolResult:
        try:
            result = await asyncio.wait_for(
                execute_registered_tool(inv.func_name, inv.args),
                timeout=self.timeout,
            )
            return ToolResult(func_name=inv.func_name, result=str(result), status="success")
        except asyncio.TimeoutError:
            return ToolResult(
                func_name=inv.func_name,
                result="Error: Local tool execution timed out.",
                status="error",
            )
        except Exception as exc:
            return ToolResult(
                func_name=inv.func_name,
                result=f"Error: Local tool execution failed: {exc}",
                status="error",
            )
