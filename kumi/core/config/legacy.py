"""Deprecated aliases kept for backward compatibility."""

from kumi.core.config.credentials import _get_provider, ensure_provider_available


def ensure_ollama_available() -> None:
    """Check that Ollama is running. Only needed when provider is ollama."""
    ensure_provider_available("ollama")


def list_local_models() -> list[str]:
    provider = _get_provider("ollama")
    return provider.list_models()


def pull_model(model_name: str) -> None:
    provider = _get_provider("ollama")
    provider.pull_model(model_name)
