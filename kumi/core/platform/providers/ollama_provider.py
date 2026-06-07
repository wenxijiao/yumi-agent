from __future__ import annotations

from typing import Any, AsyncIterator

import ollama
from kumi.core.platform.providers.base import BaseLLMProvider
from kumi.core.platform.tools.normalize import normalize_tool_calls
from kumi.logging_config import get_logger

_logger = get_logger(__name__)


def _convert_multimodal_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert OpenAI-style multimodal content to Ollama's ``images`` field."""
    converted: list[dict[str, Any]] = []
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            converted.append(msg)
            continue
        text_parts: list[str] = []
        images: list[str] = []
        for part in content:
            if part.get("type") == "text":
                text_parts.append(part["text"])
            elif part.get("type") == "image_url":
                url = part.get("image_url", {}).get("url", "")
                if "base64," in url:
                    images.append(url.split("base64,", 1)[1])
                elif url:
                    images.append(url)
        new_msg: dict[str, Any] = {**msg, "content": "\n".join(text_parts)}
        if images:
            new_msg["images"] = images
        converted.append(new_msg)
    return converted


def _extract_model_names(models) -> list[str]:
    names = []
    for model in models:
        if isinstance(model, dict):
            name = model.get("name") or model.get("model")
        else:
            name = getattr(model, "name", None) or getattr(model, "model", None)
        if name:
            names.append(name)
    return names


def _format_progress_bytes(value: int | None) -> str:
    if value is None:
        return ""
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{value}B"


class OllamaProvider(BaseLLMProvider):
    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict] | None = None,
        think: bool = False,
    ) -> AsyncIterator[dict]:
        messages = _convert_multimodal_messages(messages)
        stream = await ollama.AsyncClient().chat(
            model=model,
            messages=messages,
            think=think,
            tools=tools,
            stream=True,
        )
        last_chunk: dict | None = None
        async for chunk in stream:
            last_chunk = chunk if isinstance(chunk, dict) else None
            message = chunk.get("message", {})

            if "tool_calls" in message and message["tool_calls"]:
                normalized = normalize_tool_calls(message["tool_calls"])
                if normalized:
                    yield {"type": "tool_call", "tool_calls": normalized}
                if last_chunk:
                    pt = int(last_chunk.get("prompt_eval_count") or 0)
                    ct = int(last_chunk.get("eval_count") or 0)
                    if pt or ct:
                        yield {"type": "usage", "prompt_tokens": pt, "completion_tokens": ct, "model": model}
                return

            content = message.get("content", "")
            if content:
                yield {"type": "text", "content": content}

        if last_chunk:
            pt = int(last_chunk.get("prompt_eval_count") or 0)
            ct = int(last_chunk.get("eval_count") or 0)
            if pt or ct:
                yield {"type": "usage", "prompt_tokens": pt, "completion_tokens": ct, "model": model}

    def embed(self, model: str, text: str) -> list[float]:
        response = ollama.embed(model=model, input=text)
        return response.embeddings[0]

    def list_models(self) -> list[str]:
        listed = ollama.list()
        if isinstance(listed, dict):
            models_data = listed.get("models", [])
        else:
            models_data = getattr(listed, "models", [])
        return _extract_model_names(models_data)

    def pull_model(self, model_name: str) -> None:
        print(f"Downloading model: {model_name}")
        last_line = None

        for event in ollama.pull(model_name, stream=True):
            if not isinstance(event, dict):
                continue

            status = event.get("status", "downloading")
            completed = event.get("completed")
            total = event.get("total")

            if isinstance(completed, int) and isinstance(total, int) and total > 0:
                percent = min(100, int((completed / total) * 100))
                line = f"\r{status} {percent:3d}% ({_format_progress_bytes(completed)}/{_format_progress_bytes(total)})"
            else:
                line = f"\r{status}..."

            if line != last_line:
                print(line, end="", flush=True)
                last_line = line

        if last_line:
            print()
        print(f"Model ready: {model_name}")

    async def warm_up(self, model: str) -> None:
        try:
            await ollama.AsyncClient().generate(model=model, prompt="", keep_alive=-1)
        except Exception as exc:
            _logger.warning("Model warm-up failed: %s", exc)

    async def shutdown(self, model: str) -> None:
        try:
            await ollama.AsyncClient().generate(model=model, prompt="", keep_alive=0)
        except Exception:
            pass
