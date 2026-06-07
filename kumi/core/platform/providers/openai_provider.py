from __future__ import annotations

import json
import os
import uuid
from typing import Any, AsyncIterator

from kumi.core.platform.providers.base import BaseLLMProvider
from kumi.core.platform.tools.tool_call_normalize import normalize_tool_calls


def _normalize_messages_for_strict_openai_compat(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Adapt kumi's internal message shape to strict OpenAI / DeepSeek wire format.

    Two compat issues kumi's permissive internal storage glosses over but
    strict OpenAI-compatible providers (DeepSeek, some vLLM builds) reject:

    1. ``assistant.tool_calls[].function.arguments`` is stored as a Python
       ``dict`` (see :func:`kumi.core.platform.tools.tool_call_normalize.normalize_tool_calls`)
       but the OpenAI spec says it MUST be a JSON-encoded string. OpenAI's
       own server accepts the dict form; DeepSeek returns
       ``messages[N]: invalid type: map, expected a string``.
    2. ``role: tool`` messages must carry a ``tool_call_id`` matching the
       corresponding ``assistant.tool_calls[].id``. Kumi doesn't propagate
       these ids end-to-end (dispatcher / replay strip them), so we
       reconstruct the pairing here by position: each consecutive tool
       message consumes the next un-paired id from the preceding
       assistant turn, synthesising one if necessary.

    Internal representation is left alone; this only runs at the wire
    boundary. Returns a shallow copy.
    """

    def _gen_id() -> str:
        return f"call_{uuid.uuid4().hex[:24]}"

    out: list[dict[str, Any]] = []
    pending_ids: list[str] = []
    for msg in messages:
        role = msg.get("role")
        if role == "assistant" and msg.get("tool_calls"):
            new_calls: list[dict[str, Any]] = []
            for tc in msg["tool_calls"]:
                fn = tc.get("function") or {}
                args = fn.get("arguments")
                if isinstance(args, (dict, list)):
                    args = json.dumps(args, ensure_ascii=False)
                elif args is None:
                    args = ""
                tc_id = str(tc.get("id") or "").strip() or _gen_id()
                new_calls.append(
                    {
                        **tc,
                        "id": tc_id,
                        "type": tc.get("type") or "function",
                        "function": {**fn, "arguments": args},
                    }
                )
                pending_ids.append(tc_id)
            out.append({**msg, "tool_calls": new_calls})
        elif role == "tool":
            existing = str(msg.get("tool_call_id") or "").strip()
            if existing:
                if pending_ids and pending_ids[0] == existing:
                    pending_ids.pop(0)
                elif pending_ids:
                    # The persisted id doesn't match what we synthesised on
                    # the assistant side this turn — trust the tool row's
                    # existing id (it's what L1 stored) and drop one pending.
                    pending_ids.pop(0)
                out.append(msg)
                continue
            tc_id = pending_ids.pop(0) if pending_ids else _gen_id()
            out.append({**msg, "tool_call_id": tc_id})
        else:
            out.append(msg)
    return out


def _convert_tool_schemas(tools: list[dict] | None) -> list[dict] | None:
    """Ensure tool schemas match the OpenAI format.

    Kumi internal schemas already use the OpenAI shape, so this is
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
                "Install it with: pip install 'kumi-agent[openai]'"
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
            "messages": _normalize_messages_for_strict_openai_compat(messages),
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

            # DeepSeek (and a growing set of OpenAI-compatible providers) emits
            # chain-of-thought reasoning on a separate ``reasoning_content``
            # field next to ``content``. We surface it through the existing
            # ``thought`` chunk channel so downstream accumulation and UI
            # filtering keep working without a new event type.
            reasoning_delta = getattr(delta, "reasoning_content", None)
            if reasoning_delta:
                yield {"type": "thought", "content": reasoning_delta}

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    # Some OpenAI-compatible servers (older Azure deployments,
                    # some self-hosted vLLM builds) emit ``index = None``.
                    # Mixing ``int`` and ``None`` keys would crash the
                    # ``sorted(...)`` below, so backfill with the next slot.
                    idx = tc.index if tc.index is not None else len(collected_tool_calls)
                    if idx not in collected_tool_calls:
                        collected_tool_calls[idx] = {
                            "id": "",
                            "function": {"name": "", "arguments": ""},
                        }
                    entry = collected_tool_calls[idx]
                    # Capture the provider-issued tool_call id so the next
                    # turn's ``role: tool`` message can reference it (strict
                    # OpenAI-compatible servers like DeepSeek require this).
                    if getattr(tc, "id", None):
                        entry["id"] = tc.id
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

    async def shutdown(self, model: str) -> None:
        """Release the underlying httpx clients so connections / fds don't leak
        on lifespan teardown or PUT /config/model provider swaps."""
        client = getattr(self, "_async_client", None)
        if client is not None:
            try:
                await client.close()
            except Exception:
                pass
        sync_client = getattr(self, "_sync_client", None)
        if sync_client is not None:
            try:
                sync_client.close()
            except Exception:
                pass
