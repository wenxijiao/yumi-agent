"""API keys, provider readiness, model availability."""

import os
import sys

from kumi.core.config.model import ModelConfig
from kumi.core.config.store import load_model_config, load_saved_model_config
from kumi.core.platform.exceptions import ProviderNotReadyError


def get_api_credentials() -> dict[str, str | None]:
    """Resolve API credentials: env vars take priority, config as fallback."""
    config = load_saved_model_config()
    return {
        "openai_api_key": os.getenv("OPENAI_API_KEY") or config.openai_api_key,
        "openai_base_url": os.getenv("OPENAI_BASE_URL") or config.openai_base_url,
        "gemini_api_key": os.getenv("GEMINI_API_KEY") or config.gemini_api_key,
        "claude_api_key": os.getenv("ANTHROPIC_API_KEY") or config.claude_api_key,
        "deepseek_api_key": os.getenv("DEEPSEEK_API_KEY") or config.deepseek_api_key,
        "deepseek_base_url": os.getenv("DEEPSEEK_BASE_URL") or config.deepseek_base_url,
    }


def ensure_embedding_provider_not_deepseek(provider_name: str) -> None:
    """DeepSeek public API is not compatible with our OpenAI-style embeddings path."""
    if provider_name == "deepseek":
        raise ValueError(
            "embedding_provider cannot be 'deepseek'. Use ollama, openai, gemini, or claude for embeddings."
        )


def _get_provider(provider_name: str):
    """Create a provider instance (lazy import to avoid hard deps)."""
    from kumi.core.providers import create_provider

    return create_provider(provider_name)


def ensure_provider_available(provider_name: str) -> None:
    """Verify the provider can be used (Ollama is running, API key is set, etc.)."""
    creds = get_api_credentials()
    if provider_name == "ollama":
        provider = _get_provider("ollama")
        try:
            provider.list_models()
        except Exception as exc:
            raise ProviderNotReadyError(
                "KUMI_OLLAMA_UNAVAILABLE",
                "Cannot reach Ollama. Install Ollama and ensure the service is running.",
                hint="Check OLLAMA_HOST or run `ollama serve`.",
            ) from exc
    elif provider_name == "openai":
        if not creds["openai_api_key"]:
            raise ProviderNotReadyError(
                "KUMI_MISSING_OPENAI_KEY",
                "OpenAI API key is required for the OpenAI provider.",
                hint="Set OPENAI_API_KEY or save openai_api_key in ~/.kumi/config.json or the web UI model settings.",
            )
    elif provider_name == "gemini":
        if not creds["gemini_api_key"]:
            raise ProviderNotReadyError(
                "KUMI_MISSING_GEMINI_KEY",
                "Gemini API key is required for the Gemini provider.",
                hint="Set GEMINI_API_KEY or save gemini_api_key in ~/.kumi/config.json or the web UI model settings.",
            )
    elif provider_name == "claude":
        if not creds["claude_api_key"]:
            raise ProviderNotReadyError(
                "KUMI_MISSING_CLAUDE_KEY",
                "Anthropic API key is required for the Claude provider.",
                hint="Set ANTHROPIC_API_KEY or save claude_api_key in ~/.kumi/config.json or the web UI model settings.",
            )
    elif provider_name == "deepseek":
        if not creds["deepseek_api_key"]:
            raise ProviderNotReadyError(
                "KUMI_MISSING_DEEPSEEK_KEY",
                "DeepSeek API key is required for the DeepSeek provider.",
                hint="Set DEEPSEEK_API_KEY or save deepseek_api_key in ~/.kumi/config.json or the web UI model settings.",
            )
    else:
        from kumi.core.providers import SUPPORTED_PROVIDERS

        raise ProviderNotReadyError(
            "KUMI_UNKNOWN_PROVIDER",
            f"Unknown provider: {provider_name!r}.",
            hint=f"Supported: {', '.join(SUPPORTED_PROVIDERS)}",
        )


def is_model_available(provider_name: str, model_name: str) -> bool:
    if not model_name:
        return False
    if provider_name != "ollama":
        return True
    provider = _get_provider("ollama")
    existing = provider.list_models()
    return model_name in existing or f"{model_name}:latest" in existing


def ensure_model_ready(provider_name: str, model_name: str) -> str:
    if provider_name != "ollama":
        return model_name
    if not is_model_available(provider_name, model_name):
        provider = _get_provider("ollama")
        provider.pull_model(model_name)
    return model_name


def ensure_chat_model_configured(interactive: bool = False) -> ModelConfig:
    config = load_model_config()
    if config.chat_model:
        return config

    if interactive and sys.stdin.isatty() and sys.stdout.isatty():
        from kumi.core.config.setup_wizard import run_model_setup

        return run_model_setup(force=False)

    raise RuntimeError("No Kumi chat model is configured. Run `kumi --setup` or set `KUMI_CHAT_MODEL`.")
