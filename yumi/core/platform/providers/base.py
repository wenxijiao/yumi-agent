from __future__ import annotations

from typing import Any, AsyncIterator


class BaseLLMProvider:
    """Protocol for LLM providers.

    Every provider must implement at least ``chat_stream`` and ``embed``.
    ``list_models`` / ``pull_model`` / ``warm_up`` / ``shutdown`` are
    optional and default to no-ops.
    """

    async def chat_stream(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict] | None = None,
        think: bool = False,
    ) -> AsyncIterator[dict]:
        """Yield normalized chunks.

        Text chunks::

            {"type": "text", "content": "partial text"}

        Tool-call chunks (terminates the stream)::

            {"type": "tool_call", "tool_calls": [
                {"function": {"name": "...", "arguments": {...}}}
            ]}

        The ``tool_calls`` list must use OpenAI-style structure regardless
        of the underlying provider.
        """
        raise NotImplementedError
        yield  # pragma: no cover – make this an async generator

    def embed(self, model: str, text: str) -> list[float]:
        """Return a single embedding vector for *text*."""
        raise NotImplementedError

    def list_models(self) -> list[str]:
        """Return available model names (best-effort, may be empty)."""
        return []

    def pull_model(self, model_name: str) -> None:
        """Download / prepare a model.  No-op for cloud providers."""

    async def warm_up(self, model: str) -> None:
        """Optional: pre-load a model into memory."""

    async def shutdown(self, model: str) -> None:
        """Optional: release model resources."""
