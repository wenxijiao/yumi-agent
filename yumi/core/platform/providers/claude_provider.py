from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator

from yumi.core.platform.providers.base import BaseLLMProvider


def _convert_tools_to_claude(tools: list[dict] | None) -> list[dict] | None:
    """Convert OpenAI-style tool schemas to Anthropic tool format."""
    if not tools:
        return None

    converted = []
    for t in tools:
        fn = t.get("function", {})
        converted.append(
            {
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
            }
        )
    return converted


def _build_claude_messages(messages: list[dict[str, Any]]) -> tuple[str | None, list[dict]]:
    """Split messages into an optional system prompt and Claude content list.

    Anthropic requires system as a top-level parameter, not inside messages.
    Tool-result and assistant tool_calls messages are converted to
    Anthropic's ``tool_use`` / ``tool_result`` content block format.
    """
    system_parts: list[str] = []
    claude_messages: list[dict] = []
    pending_tool_uses: list[dict[str, str]] = []

    def _take_tool_use_id(tool_msg: dict[str, Any]) -> str:
        explicit = tool_msg.get("tool_call_id")
        if isinstance(explicit, str) and explicit.strip():
            explicit = explicit.strip()
            for idx, item in enumerate(pending_tool_uses):
                if item.get("id") == explicit:
                    pending_tool_uses.pop(idx)
                    break
            return explicit
        tool_name = str(tool_msg.get("name") or "").strip()
        if tool_name:
            for idx, item in enumerate(pending_tool_uses):
                if item.get("name") == tool_name:
                    return pending_tool_uses.pop(idx).get("id") or tool_name
        if pending_tool_uses:
            return pending_tool_uses.pop(0).get("id") or tool_name or "unknown"
        return tool_name or "unknown"

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if role == "system":
            if content:
                system_parts.append(content)
            continue

        if role == "tool":
            tool_use_id = _take_tool_use_id(msg)
            claude_messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": content or "",
                        }
                    ],
                }
            )
            continue

        if role == "assistant" and msg.get("tool_calls"):
            blocks: list[dict] = []
            if content:
                blocks.append({"type": "text", "text": content})
            for tc in msg["tool_calls"]:
                fn = tc.get("function", {})
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                tc_id = tc.get("id") or fn.get("name") or "unknown"
                pending_tool_uses.append({"id": str(tc_id), "name": str(fn.get("name", ""))})
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": tc_id,
                        "name": fn.get("name", ""),
                        "input": args,
                    }
                )
            claude_messages.append({"role": "assistant", "content": blocks})
            continue

        claude_messages.append({"role": role, "content": content or ""})

    system_text = "\n".join(system_parts) if system_parts else None
    return system_text, claude_messages


def _max_tokens_for_model(model: str) -> int:
    normalized = (model or "").lower()
    if normalized.startswith("claude-3-opus"):
        return 4096
    return 8192


class ClaudeProvider(BaseLLMProvider):
    """Provider for Anthropic Claude via the ``anthropic`` SDK."""

    def __init__(self, api_key: str | None = None):
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError(
                "The 'anthropic' package ships with yumi-agent but is missing here. "
                "Reinstall with: pip install --force-reinstall yumi-agent"
            ) from exc

        resolved_key = api_key or os.getenv("ANTHROPIC_API_KEY") or ""
        self._client = anthropic.Anthropic(api_key=resolved_key)
        self._async_client = anthropic.AsyncAnthropic(api_key=resolved_key)

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict] | None = None,
        think: bool = False,
    ) -> AsyncIterator[dict]:
        system_text, claude_messages = _build_claude_messages(messages)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": claude_messages,
            "max_tokens": _max_tokens_for_model(model),
        }

        if system_text:
            kwargs["system"] = system_text

        claude_tools = _convert_tools_to_claude(tools)
        if claude_tools:
            kwargs["tools"] = claude_tools

        async with self._async_client.messages.stream(**kwargs) as stream:
            collected_tool_calls: list[dict] = []
            current_tool_use: dict | None = None

            async for event in stream:
                if event.type == "content_block_start":
                    block = event.content_block
                    if block.type == "tool_use":
                        current_tool_use = {
                            "id": block.id,
                            "name": block.name,
                            "arguments_str": "",
                        }
                elif event.type == "content_block_delta":
                    delta = event.delta
                    if delta.type == "text_delta":
                        yield {"type": "text", "content": delta.text}
                    elif delta.type == "input_json_delta":
                        if current_tool_use is not None:
                            current_tool_use["arguments_str"] += delta.partial_json
                elif event.type == "content_block_stop":
                    if current_tool_use is not None:
                        args_str = current_tool_use["arguments_str"]
                        try:
                            args = json.loads(args_str) if args_str else {}
                        except (json.JSONDecodeError, TypeError):
                            args = {}
                        collected_tool_calls.append(
                            {
                                "id": current_tool_use["id"],
                                "type": "function",
                                "function": {
                                    "name": current_tool_use["name"],
                                    "arguments": args,
                                },
                            }
                        )
                        current_tool_use = None

            # Emit usage BEFORE tool_call — consumers stop on tool_call, so a
            # trailing usage chunk would be lost (under-counts tool-call turns).
            try:
                final_msg = await stream.get_final_message()
                u = getattr(final_msg, "usage", None)
                if u is not None:
                    pt = int(getattr(u, "input_tokens", None) or 0)
                    ct = int(getattr(u, "output_tokens", None) or 0)
                    if pt or ct:
                        yield {"type": "usage", "prompt_tokens": pt, "completion_tokens": ct, "model": model}
            except Exception:
                pass

            if collected_tool_calls:
                yield {"type": "tool_call", "tool_calls": collected_tool_calls}

    def embed(self, model: str, text: str) -> list[float]:
        raise NotImplementedError(
            "Anthropic Claude does not provide an embedding API. "
            "Use a different provider (e.g. OpenAI or Ollama) for embeddings."
        )

    def list_models(self) -> list[str]:
        return [
            "claude-sonnet-4-20250514",
            "claude-haiku-4-20250414",
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
        ]
