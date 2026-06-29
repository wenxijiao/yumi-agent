from __future__ import annotations

import warnings
from inspect import signature
from pathlib import Path
from typing import Any

from yumi.core.platform.providers.base import BaseLLMProvider

# Match on the stable middle of the message, not a start-anchored prefix, so an
# upstream change that prepends text to the warning doesn't make it leak through.
_FASTEMBED_POOLING_WARNING = r".*mean pooling instead of CLS embedding.*"
FASTEMBED_MODELS_DIR = Path.home() / ".yumi" / "models" / "fastembed"


class FastEmbedProvider(BaseLLMProvider):
    """Embedding-only provider backed by Qdrant FastEmbed."""

    def __init__(self) -> None:
        self._models: dict[str, Any] = {}

    def _model(self, model_name: str) -> Any:
        if not model_name:
            raise ValueError("FastEmbed model name cannot be empty.")
        if model_name not in self._models:
            try:
                from fastembed import TextEmbedding
            except ImportError as exc:
                raise RuntimeError(
                    "FastEmbed is not importable. Reinstall with: pip install --force-reinstall yumi-agent"
                ) from exc
            kwargs: dict[str, Any] = {"model_name": model_name}
            try:
                if "cache_dir" in signature(TextEmbedding).parameters:
                    FASTEMBED_MODELS_DIR.mkdir(parents=True, exist_ok=True)
                    kwargs["cache_dir"] = str(FASTEMBED_MODELS_DIR)
            except (TypeError, ValueError):
                pass
            with warnings.catch_warnings():
                warnings.filterwarnings("ignore", message=_FASTEMBED_POOLING_WARNING, category=UserWarning)
                self._models[model_name] = TextEmbedding(**kwargs)
        return self._models[model_name]

    def embed(self, model: str, text: str) -> list[float]:
        vectors = list(self._model(model).embed([text]))
        if not vectors:
            raise RuntimeError("FastEmbed returned no vectors.")
        return [float(v) for v in vectors[0]]

    def pull_model(self, model_name: str) -> None:
        # FastEmbed downloads lazily. Run one tiny embedding during setup so the
        # user sees download/install progress there, not during the first chat.
        self.embed(model_name, "Yumi embedding setup")

    def list_models(self) -> list[str]:
        try:
            from fastembed import TextEmbedding
        except ImportError:
            return []
        try:
            return [str(m.get("model")) for m in TextEmbedding.list_supported_models() if m.get("model")]
        except Exception:
            return []
