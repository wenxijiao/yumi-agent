"""Interactive terminal wizard for chat/embedding model selection."""

import os

from kumi.core.features.config.credentials import (
    _get_provider,
    ensure_model_ready,
    ensure_provider_available,
    get_api_credentials,
)
from kumi.core.features.config.model import (
    RECOMMENDED_CHAT_MODEL,
    RECOMMENDED_EMBEDDING_MODEL,
    RECOMMENDED_STT_MODEL,
    ModelConfig,
)
from kumi.core.features.config.paths import CONFIG_PATH
from kumi.core.features.config.store import load_model_config, load_saved_model_config, save_model_config


def _print_models(title: str, models: list[str]) -> None:
    print(title)
    if not models:
        print("  (none found)")
        return
    for index, model in enumerate(models, start=1):
        print(f"  {index}. {model}")


def _choose_installed_model(models: list[str], label: str) -> str:
    while True:
        _print_models(f"Installed {label} models:", models)
        choice = input(f"Choose a {label} model by number: ").strip()
        try:
            selected_index = int(choice)
        except ValueError:
            print("Please enter a valid number.")
            continue
        if 1 <= selected_index <= len(models):
            return models[selected_index - 1]
        print("That selection is out of range.")


def _choose_provider(label: str, *, exclude: tuple[str, ...] = ()) -> str:
    from kumi.core.platform.providers import SUPPORTED_PROVIDERS

    choices = tuple(p for p in SUPPORTED_PROVIDERS if p not in exclude)
    if not choices:
        raise RuntimeError("No providers available for this step.")

    print()
    print(f"Choose a {label} provider:")
    for i, name in enumerate(choices, 1):
        print(f"  {i}. {name}")

    while True:
        choice = input("> ").strip()
        try:
            idx = int(choice)
        except ValueError:
            print("Please enter a valid number.")
            continue
        if 1 <= idx <= len(choices):
            return choices[idx - 1]
        print("That selection is out of range.")


def _persist_cloud_api_key(provider_name: str, key: str, *, announce: bool = True) -> None:
    """Write a cloud API key to the process env and ~/.kumi/config.json."""
    if provider_name == "openai":
        env_var, field = "OPENAI_API_KEY", "openai_api_key"
    elif provider_name == "gemini":
        env_var, field = "GEMINI_API_KEY", "gemini_api_key"
    elif provider_name == "claude":
        env_var, field = "ANTHROPIC_API_KEY", "claude_api_key"
    elif provider_name == "deepseek":
        env_var, field = "DEEPSEEK_API_KEY", "deepseek_api_key"
    else:
        return
    os.environ[env_var] = key
    config = load_saved_model_config()
    setattr(config, field, key)
    save_model_config(config)
    if announce:
        print(f"  {env_var} saved to {CONFIG_PATH}.")


def _prompt_api_key(provider_name: str, *, announce_save: bool = True) -> None:
    """Prompt for API key and save to ~/.kumi/config.json."""
    creds = get_api_credentials()

    if provider_name == "openai":
        env_var = "OPENAI_API_KEY"
        existing = creds["openai_api_key"]
    elif provider_name == "gemini":
        env_var = "GEMINI_API_KEY"
        existing = creds["gemini_api_key"]
    elif provider_name == "claude":
        env_var = "ANTHROPIC_API_KEY"
        existing = creds["claude_api_key"]
    elif provider_name == "deepseek":
        env_var = "DEEPSEEK_API_KEY"
        existing = creds["deepseek_api_key"]
    else:
        return

    if existing:
        masked = existing[:4] + "..." + existing[-4:] if len(existing) > 8 else "***"
        print(f"  API key already configured ({masked}).")
        change = input("  Replace it? (y/N): ").strip().lower()
        if change != "y":
            os.environ[env_var] = existing
            return

    key = input("  API key: ").strip()
    if key:
        _persist_cloud_api_key(provider_name, key, announce=announce_save)
    else:
        print(f"  Warning: no key set; set {env_var} later if this provider fails.")


def _prompt_ollama_model(label: str) -> str:
    """Ollama-specific model chooser with pull support."""
    try:
        provider = _get_provider("ollama")
        installed = provider.list_models()
    except Exception:
        installed = []

    while True:
        print()
        print(f"Choose a {label} model:")
        options: dict[str, str] = {}
        n = 1

        if installed:
            print(f"  {n}. Use an installed {label} model")
            options[str(n)] = "installed"
            n += 1

        rec = RECOMMENDED_CHAT_MODEL if label == "chat" else RECOMMENDED_EMBEDDING_MODEL
        print(f"  {n}. Download recommended {label} model ({rec})")
        options[str(n)] = "recommended"
        n += 1

        print(f"  {n}. Enter a {label} model name manually")
        options[str(n)] = "manual"

        selected = input("> ").strip()
        action = options.get(selected)
        if not action:
            print("Please choose one of the listed options.")
            continue

        if action == "installed":
            return _choose_installed_model(installed, label)

        if action == "recommended":
            try:
                return ensure_model_ready("ollama", rec)
            except Exception as exc:
                print(f"Failed to download {rec}: {exc}")
                continue

        if action == "manual":
            name = input(f"  Enter the {label} model name: ").strip()
            if name:
                try:
                    return ensure_model_ready("ollama", name)
                except Exception as exc:
                    print(f"Failed to prepare {name}: {exc}")
                    continue
            print("  Model name cannot be empty.")


def _prompt_model_name(provider_name: str, label: str) -> str:
    """Ask the user to choose or enter a model name for the given provider."""
    if provider_name == "ollama":
        return _prompt_ollama_model(label)

    while True:
        model = input(f"  {label.capitalize()} model name: ").strip()
        if model:
            return model
        print("  Model name cannot be empty.")


_WHISPER_MODELS = ("tiny", "base", "small", "medium", "large", "turbo")


def _prompt_stt_config(config: ModelConfig) -> None:
    """Ask for optional local STT settings and mutate *config*."""
    print()
    print("Configure speech-to-text (STT) for voice messages?")
    print("  1. Skip / disable STT")
    print(f"  2. Use local Whisper multilingual model (recommended: {RECOMMENDED_STT_MODEL})")
    print("  3. Keep existing STT settings")

    while True:
        choice = input("> ").strip()
        if choice == "1":
            config.stt_provider = "disabled"
            config.stt_backend = "faster-whisper"
            config.stt_model = None
            config.stt_language = "auto"
            print("  STT disabled. You can enable it later with `kumi --setup`.")
            return
        if choice == "3":
            print(f"  Keeping STT: {config.stt_provider} / {config.stt_model or 'unset'}")
            return
        if choice == "2":
            break
        print("Please choose one of the listed options.")

    print()
    print("Choose a Whisper multilingual model:")
    hints = {
        "tiny": "lightest, fastest, lower accuracy",
        "base": "recommended starter balance",
        "small": "better accuracy, slower on low-end CPU",
        "medium": "heavy; use on stronger hardware",
        "large": "very heavy; not recommended for first setup",
        "turbo": "fast for its size, still heavier than small",
    }
    for i, name in enumerate(_WHISPER_MODELS, 1):
        default = " (default)" if name == RECOMMENDED_STT_MODEL else ""
        print(f"  {i}. {name}{default} — {hints[name]}")

    while True:
        selected = input("> ").strip()
        if not selected:
            model = RECOMMENDED_STT_MODEL
            break
        try:
            idx = int(selected)
        except ValueError:
            print("Please enter a valid number.")
            continue
        if 1 <= idx <= len(_WHISPER_MODELS):
            model = _WHISPER_MODELS[idx - 1]
            break
        print("That selection is out of range.")

    model_dir = input("  Model cache directory (Enter for ~/.kumi/models/whisper): ").strip()
    config.stt_provider = "whisper"
    config.stt_backend = "faster-whisper"
    config.stt_model = model
    config.stt_model_dir = model_dir or None
    config.stt_language = "auto"
    try:
        from kumi.core.features.stt.whisper_provider import ensure_whisper_weights_cached

        ensure_whisper_weights_cached(model=model, model_dir=config.stt_model_dir)
    except Exception as exc:
        print(f"  Warning: could not prepare Whisper weights: {exc}")
        print("  Voice transcription will retry the download on first use.")


def run_model_setup(force: bool = False) -> ModelConfig:
    current = load_saved_model_config()
    if current.chat_model and not force:
        return load_model_config()

    print("Welcome to Kumi.")
    print("Let's configure the models used by the server.")
    if current.chat_model or current.embedding_model:
        print(
            f"Current config: "
            f"chat={current.chat_provider}/{current.chat_model or 'unset'}, "
            f"embedding={current.embedding_provider}/{current.embedding_model or 'unset'}"
        )

    chat_provider = _choose_provider("chat")
    if chat_provider != "ollama":
        _prompt_api_key(chat_provider, announce_save=False)
    else:
        ensure_provider_available("ollama")
    chat_model = _prompt_model_name(chat_provider, "chat")

    embedding_provider = _choose_provider("embedding", exclude=("deepseek",))
    if embedding_provider != "ollama" and embedding_provider != chat_provider:
        _prompt_api_key(embedding_provider, announce_save=False)
    if embedding_provider == "ollama":
        try:
            ensure_provider_available("ollama")
        except RuntimeError:
            print("Warning: Ollama is not available. Embedding features will be disabled.")
    embedding_model = _prompt_model_name(embedding_provider, "embedding")

    config = load_saved_model_config()
    config.chat_provider = chat_provider
    config.chat_model = chat_model
    config.embedding_provider = embedding_provider
    config.embedding_model = embedding_model
    config.system_prompt = current.system_prompt
    _prompt_stt_config(config)
    save_model_config(config)

    print()
    print(f"Saved Kumi model config to {CONFIG_PATH}.")
    print(f"Chat: {config.chat_provider} / {config.chat_model}")
    print(f"Embedding: {config.embedding_provider} / {config.embedding_model}")
    print(f"STT: {config.stt_provider} / {config.stt_model or 'disabled'}")
    return config
