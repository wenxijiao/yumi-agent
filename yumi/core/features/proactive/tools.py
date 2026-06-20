from __future__ import annotations

from copy import deepcopy
from typing import Any

from yumi.core.platform.runtime.accessors import (
    CONFIRMATION_TOOLS,
    DISABLED_TOOLS,
    EDGE_TOOLS_REGISTRY,
)
from yumi.core.platform.tools.context_prefetch import context_prefetch_lines
from yumi.core.platform.tools.tool import TOOL_REGISTRY

# Back-compat alias: the proactive service (and tests) import this name. Class-1
# "context" prefetch now lives in platform so the chat pipeline can use it too.
proactive_context_lines = context_prefetch_lines


def _clean_schema(schema: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(schema)
    for key in (
        "allow_proactive",
        "proactive_context",
        "proactive_context_args",
        "proactive_context_description",
        "timeout",
        "require_confirmation",
        "always_include",
    ):
        out.pop(key, None)
    return out


def proactive_tool_schemas() -> list[dict[str, Any]]:
    """Return tools the model may call during proactive generation."""
    tools: list[dict[str, Any]] = []
    for name, tool_data in TOOL_REGISTRY.items():
        if name in DISABLED_TOOLS or name in CONFIRMATION_TOOLS:
            continue
        if not tool_data.get("allow_proactive"):
            continue
        tools.append(_clean_schema(tool_data["schema"]))

    for edge_tools in EDGE_TOOLS_REGISTRY.values():
        for full_name, entry in edge_tools.items():
            if full_name in DISABLED_TOOLS or full_name in CONFIRMATION_TOOLS:
                continue
            if entry.get("require_confirmation") or not entry.get("allow_proactive"):
                continue
            tools.append(_clean_schema(entry["schema"]))
    return tools
