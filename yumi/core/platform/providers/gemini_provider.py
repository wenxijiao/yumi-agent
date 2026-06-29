from __future__ import annotations

import base64
import json
import os
import re
from typing import Any, AsyncIterator

from yumi.core.platform.providers.base import BaseLLMProvider
from yumi.core.platform.providers.diagnostics import short_text, write_provider_failure_diagnostic
from yumi.logging_config import get_logger

_logger = get_logger(__name__)


def _gemini_tool_call_has_valid_predecessor(messages: list[dict[str, Any]]) -> bool:
    """Return whether a functionCall turn can legally follow the kept history."""
    idx = len(messages) - 1
    while idx >= 0 and messages[idx].get("role") == "system":
        idx -= 1
    if idx < 0:
        return False

    # Consecutive assistant text rows are merged with the functionCall into one
    # model turn later, so validate against the turn before that assistant run.
    while idx >= 0 and messages[idx].get("role") == "assistant" and not messages[idx].get("tool_calls"):
        idx -= 1
        while idx >= 0 and messages[idx].get("role") == "system":
            idx -= 1

    if idx < 0:
        return False
    return messages[idx].get("role") in ("user", "tool")


def _sanitize_gemini_tool_sequence(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sanitise message history so it satisfies Gemini's strict turn-ordering rules.

    Gemini requires:
    1. A model turn with ``function_call`` must be immediately preceded by a ``user``
       or ``function`` turn (not another ``model`` turn).
    2. Every ``function_call`` turn must be immediately followed by the correct number
       of ``tool`` (function-response) rows.
    3. ``tool`` rows must not appear without a preceding ``function_call`` turn.
    4. Consecutive turns with the same mapped role (e.g. two ``assistant`` rows that
       both become ``model``) must be avoided.

    This function drops or merges rows to satisfy those constraints.
    """
    if not messages:
        return messages

    out: list[dict[str, Any]] = []
    i = 0
    dropped_blocks = 0
    while i < len(messages):
        m = messages[i]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            tcalls = m.get("tool_calls") or []
            n = len(tcalls)
            if n == 0:
                out.append(m)
                i += 1
                continue
            if not _gemini_tool_call_has_valid_predecessor(out):
                # A persisted functionCall block can appear at the start of the
                # memory window after only system rows. Gemini rejects that
                # because functionCall must follow a user/function-response turn.
                dropped_blocks += 1
                j = i + 1
                while j < len(messages) and messages[j].get("role") == "tool":
                    j += 1
                i = j
                continue
            if any(not _gemini_tool_call_signature(tc) for tc in tcalls):
                # Gemini 3 requires functionCall history parts to carry the
                # thought_signature returned by the original model turn. Older
                # persisted rows (or rows produced by another provider) do not
                # have that opaque token, so replaying them produces a 400.
                dropped_blocks += 1
                j = i + 1
                while j < len(messages) and messages[j].get("role") == "tool":
                    j += 1
                i = j
                continue
            j = i + 1
            tools: list[dict[str, Any]] = []
            while j < len(messages) and messages[j].get("role") == "tool" and len(tools) < n:
                tools.append(messages[j])
                j += 1
            if len(tools) < n:
                dropped_blocks += 1
                i = j if tools else i + 1
                continue
            out.append(m)
            out.extend(tools)
            i = j
            continue
        if m.get("role") == "tool":
            # Standalone tool rows only reach here when they are not paired with a preceding
            # ``assistant``+``tool_calls`` in this slice (e.g. session history window cuts off
            # the model turn).  Feeding them to Gemini produces ``function`` responses without a
            # prior ``function_call`` → 400 INVALID_ARGUMENT.
            dropped_blocks += 1
            i += 1
            continue
        out.append(m)
        i += 1

    while out and out[0].get("role") == "tool":
        out.pop(0)
        dropped_blocks += 1

    if dropped_blocks:
        _logger.debug(
            "Gemini: removed %s broken tool-turn fragment(s) from message history "
            "(ephemeral/UI edge case; clear session if errors persist).",
            dropped_blocks,
        )
    return out


def _gemini_tool_call_signature(tc: Any) -> str:
    """Return the base64 Gemini thought signature stored on a tool call."""
    if not isinstance(tc, dict):
        return ""
    value = tc.get("thought_signature") or tc.get("thoughtSignature")
    if isinstance(value, str):
        return value.strip()
    return ""


def _decode_gemini_thought_signature(value: str) -> bytes | None:
    """Decode the opaque Gemini thought signature stored as base64 text."""
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return base64.b64decode(raw)
    except (ValueError, TypeError):  # binascii.Error is a ValueError subclass
        _logger.debug("Gemini: ignoring invalid thought_signature on persisted tool call")
        return None


def _summarize_gemini_contents(contents: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for content in contents:
        entry: dict[str, Any] = {"role": getattr(content, "role", None), "parts": []}
        for part in getattr(content, "parts", None) or []:
            part_summary: dict[str, Any] = {}
            text = getattr(part, "text", None)
            function_call = getattr(part, "function_call", None)
            function_response = getattr(part, "function_response", None)
            if text:
                part_summary["type"] = "text"
                part_summary["text_preview"] = short_text(text, limit=300)
            elif function_call:
                part_summary["type"] = "function_call"
                part_summary["name"] = getattr(function_call, "name", None)
                part_summary["args_preview"] = short_text(getattr(function_call, "args", None), limit=300)
                part_summary["has_thought_signature"] = bool(getattr(part, "thought_signature", None))
            elif function_response:
                part_summary["type"] = "function_response"
                part_summary["name"] = getattr(function_response, "name", None)
                part_summary["response_preview"] = short_text(getattr(function_response, "response", None), limit=300)
            else:
                part_summary["type"] = type(part).__name__
            entry["parts"].append(part_summary)
        out.append(entry)
    return out


def _merge_consecutive_gemini_contents(contents: list[Any]) -> list[Any]:
    """Merge consecutive ``Content`` objects that share the same role.

    Gemini rejects histories where two ``model`` (or two ``user``, or two
    ``function``) turns appear in a row.  Merging their ``parts`` into a
    single ``Content`` keeps the payload valid.

    This is especially important for:
    * parallel function calling — multiple ``tool`` messages must become a
      single ``function`` Content with several ``FunctionResponse`` parts;
    * text + function_call in the same assistant turn — must be a single
      ``model`` Content with both text and ``FunctionCall`` parts.
    """
    if not contents:
        return contents
    from google.genai import types

    merged: list[Any] = []
    for c in contents:
        if merged and getattr(merged[-1], "role", None) == c.role:
            merged[-1].parts.extend(c.parts)
        else:
            merged.append(types.Content(role=c.role, parts=list(c.parts or [])))
    return merged


def _convert_tools_to_gemini(tools: list[dict] | None) -> list[dict] | None:
    """Convert OpenAI-style tool schemas to Gemini function declarations."""
    if not tools:
        return None

    declarations = []
    for t in tools:
        fn = t.get("function", {})
        params = fn.get("parameters", {})

        declarations.append(
            {
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "parameters": _clean_params_for_gemini(params),
            }
        )

    return [{"function_declarations": declarations}]


def _clean_params_for_gemini(params: dict) -> dict:
    """Remove JSON Schema keys that Gemini does not accept."""
    cleaned: dict[str, Any] = {}
    allowed_keys = {"type", "properties", "required", "items", "enum", "description"}
    for k, v in params.items():
        if k not in allowed_keys:
            continue
        if k == "properties" and isinstance(v, dict):
            cleaned[k] = {prop_name: _clean_params_for_gemini(prop_val) for prop_name, prop_val in v.items()}
        elif isinstance(v, dict):
            cleaned[k] = _clean_params_for_gemini(v)
        else:
            cleaned[k] = v

    if cleaned.get("type") == "object" and "properties" not in cleaned:
        cleaned["properties"] = {}

    return cleaned


def _map_role(role: str) -> str:
    """Map OpenAI/Ollama message roles to Gemini roles."""
    if role in ("assistant",):
        return "model"
    if role in ("system",):
        return "user"
    if role in ("tool",):
        return "function"
    return role


def _openai_content_to_gemini_parts(content: Any) -> list[Any]:
    """Convert OpenAI ``content`` (string or multimodal parts list) to ``google.genai`` ``Part`` list."""
    from google.genai import types

    if content is None:
        return [types.Part(text="")]
    if isinstance(content, str):
        return [types.Part(text=content)]
    if not isinstance(content, list):
        return [types.Part(text=str(content))]

    parts: list[Any] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            parts.append(types.Part(text=str(block.get("text", ""))))
        elif btype == "image_url":
            url = ""
            iu = block.get("image_url")
            if isinstance(iu, dict):
                url = (iu.get("url") or "").strip()
            elif isinstance(iu, str):
                url = iu.strip()
            if url.startswith("data:"):
                try:
                    comma = url.find(",")
                    if comma == -1:
                        parts.append(types.Part(text="[invalid image data]"))
                        continue
                    header = url[:comma]
                    b64 = url[comma + 1 :]
                    m = re.match(r"data:([^;]+)", header)
                    mime = m.group(1) if m else "image/jpeg"
                    raw = base64.standard_b64decode(b64)
                    parts.append(types.Part(inline_data=types.Blob(mime_type=mime, data=raw)))
                except Exception as exc:
                    _logger.warning("Gemini: could not decode inline image: %s", exc)
                    parts.append(types.Part(text="[image could not be decoded]"))
            else:
                parts.append(types.Part(text=f"[remote image URL not inlined; paste or upload to Yumi: {url[:120]}]"))
        else:
            parts.append(types.Part(text=str(block)))

    return parts if parts else [types.Part(text="")]


class GeminiProvider(BaseLLMProvider):
    """Provider for Google Gemini via the ``google-genai`` SDK."""

    def __init__(self, api_key: str | None = None):
        try:
            from google import genai
        except ImportError as exc:
            raise ImportError(
                "The 'google-genai' package ships with yumi but is missing here. "
                "Reinstall with: pip install --force-reinstall yumi"
            ) from exc

        resolved_key = api_key or os.getenv("GEMINI_API_KEY") or ""
        self._client = genai.Client(api_key=resolved_key)

    def _build_contents(self, messages: list[dict[str, Any]]) -> tuple[str | None, list[Any]]:
        """Split messages into an optional system instruction and Gemini content list.

        After building individual Content objects the method merges consecutive
        same-role entries so the payload satisfies Gemini's turn-ordering rules
        (e.g. parallel tool responses → single ``function`` Content).
        """
        from google.genai import types

        system_instruction = None
        contents: list[Any] = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                if system_instruction is None:
                    system_instruction = content
                else:
                    system_instruction += "\n" + content
                continue

            if role == "tool":
                contents.append(
                    types.Content(
                        role="function",
                        parts=[
                            types.Part(
                                function_response=types.FunctionResponse(
                                    name=msg.get("name", "unknown"),
                                    response={"result": content},
                                )
                            )
                        ],
                    )
                )
                continue

            if role == "assistant" and msg.get("tool_calls"):
                parts = []
                tc_content = msg.get("content", "")
                if tc_content:
                    parts.extend(_openai_content_to_gemini_parts(tc_content))
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {})
                    args = fn.get("arguments", {})
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except (json.JSONDecodeError, TypeError):
                            args = {}
                    signature = _decode_gemini_thought_signature(_gemini_tool_call_signature(tc))
                    parts.append(
                        types.Part(
                            function_call=types.FunctionCall(
                                name=fn.get("name", ""),
                                args=args,
                            ),
                            thought_signature=signature,
                        )
                    )
                contents.append(types.Content(role="model", parts=parts))
                continue

            gemini_role = _map_role(role)
            gemini_parts = _openai_content_to_gemini_parts(content)
            contents.append(types.Content(role=gemini_role, parts=gemini_parts))

        contents = _merge_consecutive_gemini_contents(contents)
        return system_instruction, contents

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict] | None = None,
        think: bool = False,
    ) -> AsyncIterator[dict]:
        from google.genai import types

        cleaned = _sanitize_gemini_tool_sequence(list(messages))
        system_instruction, contents = self._build_contents(cleaned)

        config: dict[str, Any] = {}
        if system_instruction:
            config["system_instruction"] = system_instruction

        gemini_tools = _convert_tools_to_gemini(tools)

        try:
            response = self._client.models.generate_content_stream(
                model=model,
                contents=contents,
                config=types.GenerateContentConfig(
                    **config,
                    tools=gemini_tools,
                )
                if (config or gemini_tools)
                else None,
            )

            collected_tool_calls: list[dict] = []
            last_usage = None

            for chunk in response:
                um = getattr(chunk, "usage_metadata", None)
                if um is not None:
                    last_usage = um
                if not chunk.candidates:
                    continue

                cand = chunk.candidates[0]
                content = getattr(cand, "content", None)
                if content is None:
                    continue
                parts = getattr(content, "parts", None)
                if not parts:
                    continue

                for part in parts:
                    if part.function_call:
                        fc = part.function_call
                        args = dict(fc.args) if fc.args else {}
                        call: dict[str, Any] = {"function": {"name": fc.name, "arguments": args}}
                        signature = getattr(part, "thought_signature", None)
                        if signature:
                            call["thought_signature"] = base64.b64encode(signature).decode("ascii")
                        collected_tool_calls.append(call)
                    elif part.text:
                        yield {"type": "text", "content": part.text}

            # Emit usage BEFORE tool_call — consumers stop on tool_call, so a
            # trailing usage chunk would be lost (under-counts tool-call turns).
            if last_usage is not None:
                pt = int(getattr(last_usage, "prompt_token_count", None) or 0)
                ct = int(getattr(last_usage, "candidates_token_count", None) or 0)
                if pt or ct:
                    yield {"type": "usage", "prompt_tokens": pt, "completion_tokens": ct, "model": model}

            if collected_tool_calls:
                yield {"type": "tool_call", "tool_calls": collected_tool_calls}
        except Exception as exc:
            path = write_provider_failure_diagnostic(
                exc=exc,
                provider="gemini",
                model=model,
                messages=messages,
                tools=tools,
                extra={
                    "cleaned_messages": len(cleaned),
                    "system_instruction_preview": short_text(system_instruction),
                    "gemini_contents": _summarize_gemini_contents(contents),
                },
            )
            if path:
                _logger.error("Gemini request failed; wrote diagnostic snapshot to %s", path)
            raise

    def embed(self, model: str, text: str) -> list[float]:
        result = self._client.models.embed_content(
            model=model,
            contents=text,
        )
        return list(result.embeddings[0].values)

    def list_models(self) -> list[str]:
        try:
            models = self._client.models.list()
            names = []
            for m in models:
                name = getattr(m, "name", None)
                if name:
                    names.append(name)
            return names
        except Exception:
            return []

    async def shutdown(self, model: str) -> None:
        """Release the underlying genai client (and any httpx connection pool
        it holds) on lifespan teardown / provider swap."""
        client = getattr(self, "_client", None)
        if client is None:
            return
        # google-genai exposes either an async close or a context manager;
        # try the safer paths and fall through silently if the SDK changes.
        for name in ("aclose", "close"):
            fn = getattr(client, name, None)
            if fn is None:
                continue
            try:
                result = fn()
                if hasattr(result, "__await__"):
                    await result
                return
            except Exception:
                continue
