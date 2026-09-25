"""Conservative input estimates and request-local generation limits."""

from __future__ import annotations

import json
from copy import deepcopy


def token_estimate(value) -> int:
    """Estimate text/structure, counting pixels separately from base64 transport."""
    if isinstance(value, dict):
        if value.get("type") == "image_url":
            return 4096
        return 4 + sum(token_estimate(k) + token_estimate(v) for k, v in value.items())
    if isinstance(value, list):
        return 2 + sum(token_estimate(item) for item in value)
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    # Byte-based estimate is deliberately conservative for non-Latin scripts.
    return (len(text.encode("utf-8")) + 2) // 3


def fit_tool_schemas(tools: list[dict], *, budget: int, priority_names: list[str] | None = None) -> list[dict]:
    """Keep discovery reachable and prefer the most recently discovered functions."""
    priorities = ["discover_app_tools", "browse_app_tools", *(priority_names or [])]
    rank = {name: index for index, name in enumerate(dict.fromkeys(priorities))}
    candidates = sorted(tools, key=lambda tool: rank.get(tool.get("function", {}).get("name"), len(rank)))
    chosen = set()
    used = 2
    for tool in candidates:
        cost = token_estimate(tool)
        if used + cost <= budget:
            chosen.add(tool["function"]["name"])
            used += cost
    # Preserve the original order for the provider's prompt cache.
    return [tool for tool in tools if tool["function"]["name"] in chosen]


def fit_prompt(
    messages: list[dict], tools: list | None, *, budget: int, current_user_index: int | None = None
) -> list[dict]:
    """Trim completed history as whole turns. The active task and tool IDs stay.

    Required rules and recalled facts are never silently dropped. If the
    remaining task cannot fit, stop before asking the provider to accept it.
    """
    out = deepcopy(messages)
    current = current_user_index
    if current is None:
        current = max((i for i, m in enumerate(out) if m.get("role") == "user"), default=len(out))
    tools_size = token_estimate(tools or [])

    def size():
        return token_estimate(out) + tools_size

    while size() > budget:
        starts = [i for i, m in enumerate(out[:current]) if m.get("role") == "user"]
        if not starts:
            break
        start = starts[0]
        end = starts[1] if len(starts) > 1 else current
        # Preserve runtime/retrieval system notes between completed history and
        # the active user prompt, while removing the old dialogue/tool span.
        kept = [m for m in out[start:end] if m.get("role") == "system"]
        current -= end - start - len(kept)
        out[start:end] = kept
    if size() > budget:
        for max_chars in (2000, 1000, 500):
            for message in out:
                content = message.get("content")
                if message.get("role") == "tool" and isinstance(content, str) and len(content) > max_chars:
                    message["content"] = (
                        content[:max_chars] + "\n[Result shortened to fit this request; do not assume omitted details.]"
                    )
            if size() <= budget:
                break
    if size() > budget:
        raise ValueError(
            "This request exceeds the available context budget. Shorten the request or restart the conversation."
        )
    return out
