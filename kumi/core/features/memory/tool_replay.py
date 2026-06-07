"""Serialize/deserialize OpenAI-style tool turns for LanceDB persistence and LLM replay."""

from __future__ import annotations

import json
from typing import Any

from kumi.core.features.memory.constants import KUMI_V1_TOOL_CALLS, KUMI_V1_TOOL_RESULT
from kumi.core.platform.tools.normalize import normalize_tool_calls


def message_hidden_from_chat_ui(message: dict) -> bool:
    """True for DB rows that exist only to persist tool_calls for LLM replay (not end-user chat)."""
    if message.get("role") != "assistant":
        return False
    return str(message.get("content") or "").startswith(KUMI_V1_TOOL_CALLS)


def persist_openai_messages(memory: Any, messages: list[dict[str, Any]]) -> None:
    """Persist assistant+tool_calls and tool rows so ``get_context`` can replay them."""
    for m in messages:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            safe_calls = normalize_tool_calls(m["tool_calls"])
            if not safe_calls:
                continue
            data = {"tool_calls": safe_calls}
            text_content = (m.get("content") or "").strip()
            if text_content:
                data["content"] = text_content
            # Capture chain-of-thought reasoning when the provider supplied
            # one (DeepSeek thinking-mode etc.). The spec requires we echo it
            # back on every subsequent turn that follows a tool-call, so we
            # have to round-trip it through storage.
            reasoning = (m.get("reasoning_content") or "").strip()
            if reasoning:
                data["reasoning_content"] = reasoning
            payload = json.dumps(data, ensure_ascii=False)
            memory.add_message("assistant", KUMI_V1_TOOL_CALLS + payload)
        elif role == "tool":
            name = (m.get("name") or "tool").strip() or "tool"
            body = str(m.get("content", ""))
            payload = json.dumps({"name": name, "content": body}, ensure_ascii=False)
            memory.add_message("tool", KUMI_V1_TOOL_RESULT + payload)
