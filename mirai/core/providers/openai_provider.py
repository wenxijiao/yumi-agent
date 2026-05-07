from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator

from mirai.core.providers.base import BaseLLMProvider
from mirai.core.tool_call_normalize import normalize_tool_calls


def _convert_tool_schemas(tools: list[dict] | None) -> list[dict] | None:
    """Ensure tool schemas match the OpenAI format.

    Mirai internal schemas already use the OpenAI shape, so this is
    mostly a pass-through.  We strip any extra keys the API would reject.
    """
    if not tools:
        return None
    converted = []
    for t in tools:
        fn = t.get("function", {})
        converted.append(
            {
                "type": "function",
                "function": {
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "parameters": fn.get("parameters", {}),
                },
            }
        )
    return converted


class OpenAIProvider(BaseLLMProvider):
    """Provider for OpenAI and any OpenAI-compatible API.

    Covers: OpenAI, Azure OpenAI, vLLM, LM Studio, Groq, Together AI,
    DeepSeek, and any service that speaks the OpenAI chat completions
    protocol.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
    ):
        try:
            from openai import AsyncOpenAI, OpenAI
        except ImportError as exc:
            raise ImportError(
                "The 'openai' package is required for the OpenAI / DeepSeek provider. "
                "Install it with: pip install 'mirai-agent[openai]'"
            ) from exc

        resolved_key = api_key or os.getenv("OPENAI_API_KEY") or ""
        resolved_url = base_url or os.getenv("OPENAI_BASE_URL") or None

        self._sync_client = OpenAI(api_key=resolved_key, base_url=resolved_url)
        self._async_client = AsyncOpenAI(api_key=resolved_key, base_url=resolved_url)

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict] | None = None,
        think: bool = False,
    ) -> AsyncIterator[dict]:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }

        converted_tools = _convert_tool_schemas(tools)
        if converted_tools:
            kwargs["tools"] = converted_tools

        stream = await self._async_client.chat.completions.create(**kwargs)

        collected_tool_calls: dict[int, dict] = {}
        usage_payload = None

        async for chunk in stream:
            u = getattr(chunk, "usage", None)
            if u is not None:
                usage_payload = u
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    # Some OpenAI-compatible servers (older Azure deployments,
                    # some self-hosted vLLM builds) emit ``index = None``.
                    # Mixing ``int`` and ``None`` keys would crash the
                    # ``sorted(...)`` below, so backfill with the next slot.
                    idx = tc.index if tc.index is not None else len(collected_tool_calls)
                    if idx not in collected_tool_calls:
                        collected_tool_calls[idx] = {
                            "function": {"name": "", "arguments": ""},
                        }
                    entry = collected_tool_calls[idx]
                    if tc.function:
                        if tc.function.name:
                            entry["function"]["name"] += tc.function.name
                        if tc.function.arguments:
                            entry["function"]["arguments"] += tc.function.arguments

            content = delta.content
            if content:
                yield {"type": "text", "content": content}

        if collected_tool_calls:
            tool_calls_list = []
            for idx in sorted(collected_tool_calls):
                tc = collected_tool_calls[idx]
                args_str = tc["function"]["arguments"]
                try:
                    tc["function"]["arguments"] = json.loads(args_str)
                except (json.JSONDecodeError, TypeError):
                    tc["function"]["arguments"] = {}
                tool_calls_list.append(tc)

            tool_calls_list = normalize_tool_calls(tool_calls_list)
            if tool_calls_list:
                yield {"type": "tool_call", "tool_calls": tool_calls_list}

        if usage_payload is not None:
            pt = int(getattr(usage_payload, "prompt_tokens", None) or 0)
            ct = int(getattr(usage_payload, "completion_tokens", None) or 0)
            if pt or ct:
                yield {"type": "usage", "prompt_tokens": pt, "completion_tokens": ct, "model": model}

    def embed(self, model: str, text: str) -> list[float]:
        response = self._sync_client.embeddings.create(model=model, input=text)
        return list(response.data[0].embedding)

    def list_models(self) -> list[str]:
        try:
            models = self._sync_client.models.list()
            return [m.id for m in models.data]
        except Exception:
            return []
