"""Process-wide embedding provider for Memory (set by API lifespan)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yumi.core.platform.providers.base import BaseLLMProvider

_embed_provider: "BaseLLMProvider | None" = None


class _MeteringEmbedWrapper:
    """Wrap ``embed()`` and forward usage estimates through the quota plugin."""

    def __init__(self, inner: "BaseLLMProvider"):
        self._inner = inner

    def embed(self, model: str, text: str) -> list[float]:
        out = self._inner.embed(model, text)
        try:
            from yumi.core.platform.plugins import get_current_identity, get_quota_policy

            est = max(1, len(text) // 4)
            get_quota_policy().record_embed_tokens(get_current_identity(), est, model=model or "unknown")
        except Exception:
            pass
        return out

    def __getattr__(self, name: str):
        return getattr(self._inner, name)


def set_embed_provider(provider: "BaseLLMProvider | None") -> None:
    global _embed_provider
    if provider is None:
        _embed_provider = None
        return
    _embed_provider = _MeteringEmbedWrapper(provider)


def get_embed_provider() -> "BaseLLMProvider | None":
    return _embed_provider


def is_degenerate_vector(vec: list | tuple | None) -> bool:
    """True if vector is missing or all near-zero (unsuitable for ANN search)."""
    if vec is None:
        return True
    try:
        return all(abs(float(x)) < 1e-12 for x in vec)
    except (TypeError, ValueError):
        return True
