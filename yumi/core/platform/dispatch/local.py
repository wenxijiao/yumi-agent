"""Execute a registered local tool with timeout and structured error capture."""

from __future__ import annotations

import asyncio
import json

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
            text = json.dumps(result, ensure_ascii=False) if isinstance(result, (dict, list)) else str(result)
            return ToolResult(func_name=inv.func_name, result=text, status="success")
        except asyncio.TimeoutError:
            return ToolResult(
                func_name=inv.func_name,
                result="Tool execution timed out; outcome unknown. The action may still complete. Do not automatically retry it.",
                status="unknown",
            )
        except Exception as exc:
            return ToolResult(
                func_name=inv.func_name,
                result=f"Error: Local tool execution failed: {exc}",
                status="error",
            )
