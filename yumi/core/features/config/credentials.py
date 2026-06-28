"""API keys, provider readiness, model availability."""

import importlib.util
import os
import sys

from yumi.core.features.config.model import EMBEDDING_CAPABLE_PROVIDERS, ModelConfig
from yumi.core.features.config.store import load_model_config, load_saved_model_config
from yumi.core.platform.exceptions import ProviderNotReadyError


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
        "grok_api_key": os.getenv("XAI_API_KEY") or os.getenv("GROK_API_KEY") or config.grok_api_key,
        "grok_base_url": os.getenv("XAI_BASE_URL") or os.getenv("GROK_BASE_URL") or config.grok_base_url,
    }


def ensure_embedding_provider_supported(provider_name: str, *, allow_disabled: bool = True) -> None:
    """Verify the configured embedding provider exposes a text-embedding API."""
    name = (provider_name or "").strip()
    if allow_disabled and name == "disabled":
        return
    if name in EMBEDDING_CAPABLE_PROVIDERS:
        return
    choices = ", ".join((*EMBEDDING_CAPABLE_PROVIDERS, "disabled" if allow_disabled else ""))
    choices = choices.rstrip(", ")
    raise ValueError(
        f"embedding_provider must be one of: {choices}. {name!r} does not expose a supported embedding API."
    )


def ensure_embedding_provider_not_deepseek(provider_name: str) -> None:
    """Backward-compatible wrapper for older imports."""
    ensure_embedding_provider_supported(provider_name)


def _get_provider(provider_name: str):
    """Create a provider instance (lazy import to avoid hard deps)."""
    from yumi.core.platform.providers import create_provider

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
                "YUMI_OLLAMA_UNAVAILABLE",
                "Cannot reach Ollama. Install Ollama and ensure the service is running.",
                hint="Check OLLAMA_HOST or run `ollama serve`.",
            ) from exc
    elif provider_name == "openai":
        if not creds["openai_api_key"]:
            raise ProviderNotReadyError(
                "YUMI_MISSING_OPENAI_KEY",
                "OpenAI API key is required for the OpenAI provider.",
                hint="Set OPENAI_API_KEY or save openai_api_key in ~/.yumi/config.json or the web UI model settings.",
            )
    elif provider_name == "gemini":
        if not creds["gemini_api_key"]:
            raise ProviderNotReadyError(
                "YUMI_MISSING_GEMINI_KEY",
                "Gemini API key is required for the Gemini provider.",
                hint="Set GEMINI_API_KEY or save gemini_api_key in ~/.yumi/config.json or the web UI model settings.",
            )
    elif provider_name == "claude":
        if not creds["claude_api_key"]:
            raise ProviderNotReadyError(
                "YUMI_MISSING_CLAUDE_KEY",
                "Anthropic API key is required for the Claude provider.",
                hint="Set ANTHROPIC_API_KEY or save claude_api_key in ~/.yumi/config.json or the web UI model settings.",
            )
    elif provider_name == "deepseek":
        if not creds["deepseek_api_key"]:
            raise ProviderNotReadyError(
                "YUMI_MISSING_DEEPSEEK_KEY",
                "DeepSeek API key is required for the DeepSeek provider.",
                hint="Set DEEPSEEK_API_KEY or save deepseek_api_key in ~/.yumi/config.json or the web UI model settings.",
            )
    elif provider_name == "grok":
        if not creds["grok_api_key"]:
            raise ProviderNotReadyError(
                "YUMI_MISSING_GROK_KEY",
                "Grok API key is required for the Grok provider.",
                hint="Set XAI_API_KEY or save grok_api_key in ~/.yumi/config.json or the web UI model settings.",
            )
    elif provider_name == "fastembed":
        if importlib.util.find_spec("fastembed") is None:
            raise ProviderNotReadyError(
                "YUMI_MISSING_FASTEMBED",
                "FastEmbed is required for local embeddings.",
                hint="Run `yumi --setup` and choose Local embeddings, or install `pip install 'yumi-agent[embed]'`.",
            )
    else:
        from yumi.core.platform.providers import ALL_PROVIDER_NAMES

        raise ProviderNotReadyError(
            "YUMI_UNKNOWN_PROVIDER",
            f"Unknown provider: {provider_name!r}.",
            hint=f"Supported: {', '.join(ALL_PROVIDER_NAMES)}",
        )


# Cloud providers that need an API key, with the env var + config field that supply it.
_KEYED_PROVIDERS: dict[str, tuple[str, str]] = {
    "openai": ("OPENAI_API_KEY", "openai_api_key"),
    "gemini": ("GEMINI_API_KEY", "gemini_api_key"),
    "claude": ("ANTHROPIC_API_KEY", "claude_api_key"),
    "deepseek": ("DEEPSEEK_API_KEY", "deepseek_api_key"),
    "grok": ("XAI_API_KEY", "grok_api_key"),
    "dashscope": ("DASHSCOPE_API_KEY", "tts_api_key"),  # shared STT/TTS key
}


def _provider_key_present(provider_name: str, config) -> bool:
    """True if the API key for *provider_name* is available (env or config)."""
    name = (provider_name or "").strip().lower()
    pair = _KEYED_PROVIDERS.get(name)
    if pair is None:
        return True  # provider needs no key (ollama / fastembed / system / whisper / qwen)
    env_var, field = pair
    if os.getenv(env_var):
        return True
    if name == "grok" and os.getenv("GROK_API_KEY"):  # XAI_API_KEY is primary; GROK_API_KEY also accepted
        return True
    return bool((getattr(config, field, None) or "").strip())


def missing_credentials(config) -> list[dict]:
    """List configured cloud features whose API key is missing.

    Each entry: ``{feature, provider, env_var, config_field, fatal}``. ``fatal``
    marks the chat model (the server can't run without it); memory/voice features
    are non-fatal — they degrade until the key is added. Local/no-key providers
    (ollama, fastembed, system, whisper, qwen) never appear here.
    """
    features = [
        ("chat model", config.chat_provider, True),
        ("memory embeddings", config.embedding_provider, False),
        ("voice input (STT)", config.stt_provider, False),
        ("spoken replies (TTS)", config.tts_provider, False),
    ]
    issues: list[dict] = []
    for feature, provider, fatal in features:
        name = (provider or "").strip().lower()
        if name in ("", "disabled", "none", "off") or name not in _KEYED_PROVIDERS:
            continue
        if _provider_key_present(name, config):
            continue
        env_var, field = _KEYED_PROVIDERS[name]
        issues.append({"feature": feature, "provider": name, "env_var": env_var, "config_field": field, "fatal": fatal})
    return issues


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


# API-key env var -> provider, in priority order. Lets a cloud user boot with
# nothing but e.g. OPENAI_API_KEY set (Docker/CI friendly) — no wizard needed.
_ENV_KEY_TO_PROVIDER: tuple[tuple[str, str], ...] = (
    ("OPENAI_API_KEY", "openai"),
    ("ANTHROPIC_API_KEY", "claude"),
    ("GEMINI_API_KEY", "gemini"),
    ("DEEPSEEK_API_KEY", "deepseek"),
    ("XAI_API_KEY", "grok"),
    ("GROK_API_KEY", "grok"),
)


def infer_chat_from_env() -> tuple[str, str] | None:
    """Infer ``(provider, chat_model)`` from the environment, or ``None``.

    Used when no chat model is configured: if a cloud API key is present we pick
    that provider plus its recommended default model, so `yumi --server` and
    Docker images work with zero setup. ``YUMI_CHAT_PROVIDER`` (with optional
    ``YUMI_CHAT_MODEL``) takes precedence over key sniffing.
    """
    from yumi.core.features.config.model import RECOMMENDED_CHAT_MODELS

    def _default_model(provider: str) -> str | None:
        return os.getenv("YUMI_CHAT_MODEL") or (RECOMMENDED_CHAT_MODELS.get(provider) or [None])[0]

    explicit = os.getenv("YUMI_CHAT_PROVIDER")
    if explicit:
        model = _default_model(explicit)
        return (explicit, model) if model else None

    for env_var, provider in _ENV_KEY_TO_PROVIDER:
        if os.getenv(env_var):
            model = _default_model(provider)
            if model:
                return provider, model
    return None


def ensure_chat_model_configured(interactive: bool = False) -> ModelConfig:
    config = load_model_config()
    if config.chat_model:
        return config

    inferred = infer_chat_from_env()
    if inferred:
        from yumi.core.features.config.store import save_model_config

        provider, model = inferred
        config.chat_provider = provider
        config.chat_model = model
        try:
            save_model_config(config)
        except Exception:
            pass  # read-only config dir (e.g. Docker): in-memory config still works
        return config

    if interactive and sys.stdin.isatty() and sys.stdout.isatty():
        from yumi.core.features.config.setup_wizard import run_model_setup

        return run_model_setup(force=False)

    raise RuntimeError(
        "No Yumi chat model is configured. Run `yumi --setup`, set `YUMI_CHAT_MODEL`, "
        "or provide a cloud API key (e.g. OPENAI_API_KEY)."
    )
