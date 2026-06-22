from __future__ import annotations

from yumi.core.platform.providers.base import BaseLLMProvider

SUPPORTED_PROVIDERS = ("ollama", "openai", "gemini", "claude", "deepseek", "grok")
EMBEDDING_ONLY_PROVIDERS = ("fastembed",)
ALL_PROVIDER_NAMES = (*SUPPORTED_PROVIDERS, *EMBEDDING_ONLY_PROVIDERS)


def create_provider(
    provider_name: str,
    *,
    credentials: dict[str, str | None] | None = None,
) -> BaseLLMProvider:
    """Instantiate a provider by name.

    Credentials default to env var > ~/.yumi/config.json; pass *credentials* to override.
    """
    from yumi.core.features.config import get_api_credentials

    creds = credentials if credentials is not None else get_api_credentials()

    if provider_name == "ollama":
        from yumi.core.platform.providers.ollama_provider import OllamaProvider

        return OllamaProvider()

    if provider_name == "openai":
        from yumi.core.platform.providers.openai_provider import OpenAIProvider

        return OpenAIProvider(
            api_key=creds["openai_api_key"],
            base_url=creds["openai_base_url"],
        )

    if provider_name == "gemini":
        from yumi.core.platform.providers.gemini_provider import GeminiProvider

        return GeminiProvider(api_key=creds["gemini_api_key"])

    if provider_name == "claude":
        from yumi.core.platform.providers.claude_provider import ClaudeProvider

        return ClaudeProvider(api_key=creds["claude_api_key"])

    if provider_name == "deepseek":
        from yumi.core.features.config.model import DEFAULT_DEEPSEEK_BASE_URL
        from yumi.core.platform.providers.openai_provider import OpenAIProvider

        base = creds["deepseek_base_url"] or DEFAULT_DEEPSEEK_BASE_URL
        return OpenAIProvider(api_key=creds["deepseek_api_key"], base_url=base)

    if provider_name == "grok":
        from yumi.core.features.config.model import DEFAULT_GROK_BASE_URL
        from yumi.core.platform.providers.openai_provider import OpenAIProvider

        base = creds["grok_base_url"] or DEFAULT_GROK_BASE_URL
        return OpenAIProvider(api_key=creds["grok_api_key"], base_url=base)

    if provider_name == "fastembed":
        from yumi.core.platform.providers.fastembed_provider import FastEmbedProvider

        return FastEmbedProvider()

    raise ValueError(f"Unknown provider: '{provider_name}'. Supported providers: {', '.join(ALL_PROVIDER_NAMES)}")


__all__ = [
    "ALL_PROVIDER_NAMES",
    "BaseLLMProvider",
    "EMBEDDING_ONLY_PROVIDERS",
    "SUPPORTED_PROVIDERS",
    "create_provider",
]
