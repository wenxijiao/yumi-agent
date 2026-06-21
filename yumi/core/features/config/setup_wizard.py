"""Interactive terminal wizard for chat/embedding model selection."""

import os

from yumi.core.features.config.credentials import (
    _get_provider,
    ensure_embedding_provider_supported,
    ensure_model_ready,
    ensure_provider_available,
    get_api_credentials,
    is_model_available,
)
from yumi.core.features.config.model import (
    RECOMMENDED_CHAT_MODEL,
    RECOMMENDED_CHAT_MODELS,
    RECOMMENDED_EMBEDDING_MODEL,
    RECOMMENDED_EMBEDDING_MODELS,
    RECOMMENDED_STT_MODEL,
    ModelConfig,
)
from yumi.core.features.config.paths import CONFIG_PATH
from yumi.core.features.config.store import load_model_config, load_saved_model_config, save_model_config


def _api_key_target(provider_name: str) -> tuple[str, str] | None:
    if provider_name == "openai":
        return "OPENAI_API_KEY", "openai_api_key"
    if provider_name == "gemini":
        return "GEMINI_API_KEY", "gemini_api_key"
    if provider_name == "claude":
        return "ANTHROPIC_API_KEY", "claude_api_key"
    if provider_name == "deepseek":
        return "DEEPSEEK_API_KEY", "deepseek_api_key"
    return None


def _existing_api_key(provider_name: str) -> str | None:
    target = _api_key_target(provider_name)
    if target is None:
        return None
    _env_var, field = target
    return get_api_credentials().get(field)


def _mask_secret(value: str) -> str:
    return value[:4] + "..." + value[-4:] if len(value) > 8 else "***"


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


def _persist_cloud_api_key(provider_name: str, key: str, *, announce: bool = True) -> None:
    """Write a cloud API key to the process env and ~/.yumi/config.json."""
    target = _api_key_target(provider_name)
    if target is None:
        return
    env_var, field = target
    os.environ[env_var] = key
    config = load_saved_model_config()
    setattr(config, field, key)
    save_model_config(config)
    if announce:
        print(f"  {env_var} saved to {CONFIG_PATH}.")


def _prompt_api_key(provider_name: str, *, announce_save: bool = True) -> None:
    """Prompt for API key and save to ~/.yumi/config.json."""
    target = _api_key_target(provider_name)
    if target is None:
        return
    env_var, _field = target
    existing = _existing_api_key(provider_name)

    if existing:
        print(f"  API key already configured ({_mask_secret(existing)}).")
        change = input("  Replace it? (y/N): ").strip().lower()
        if change != "y":
            os.environ[env_var] = existing
            return

    key = input("  API key: ").strip()
    if key:
        _persist_cloud_api_key(provider_name, key, announce=announce_save)
    else:
        print(f"  Warning: no key set; set {env_var} later if this provider fails.")


def _prompt_ollama_model(label: str) -> str | None:
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
        n += 1

        print(f"  {n}. Back")
        options[str(n)] = "back"

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

        if action == "back":
            return None


def _prompt_model_name(provider_name: str, label: str) -> str | None:
    """Ask the user to choose or enter a model name for the given provider."""
    if provider_name == "ollama":
        return _prompt_ollama_model(label)

    while True:
        model = input(f"  {label.capitalize()} model name (Enter to go back): ").strip()
        if model:
            return model
        return None


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
            print("  STT disabled. You can enable it later with `yumi --setup`.")
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

    model_dir = input("  Model cache directory (Enter for ~/.yumi/models/whisper): ").strip()
    config.stt_provider = "whisper"
    config.stt_backend = "faster-whisper"
    config.stt_model = model
    config.stt_model_dir = model_dir or None
    config.stt_language = "auto"

    from yumi.core.features.config.feature_install import ensure_feature_installed

    if not ensure_feature_installed("stt"):
        print("  STT settings saved, but the package isn't installed yet — skipping model download.")
        print("  Re-run `yumi --setup` after installing to cache the weights.")
        return
    try:
        from yumi.core.features.stt.whisper_provider import ensure_whisper_weights_cached

        ensure_whisper_weights_cached(model=model, model_dir=config.stt_model_dir)
    except Exception as exc:
        print(f"  Warning: could not prepare Whisper weights: {exc}")
        print("  Voice transcription will retry the download on first use.")


# ── text-to-speech (spoken replies) ─────────────────────────────────────────

# Curated voice shortlists (both backends accept more — type a name to override).
_TTS_DASHSCOPE_VOICES = ("Cherry", "Serena", "Ethan", "Chelsie", "Dylan", "Eric", "Ryan", "Jada", "Sunny")
_TTS_QWEN_SPEAKERS = ("Ryan", "Vivian", "Serena", "Dylan", "Eric", "Aiden", "Uncle_Fu", "Ono_Anna", "Sohee")
_QWEN_DEFAULT_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"


def _prompt_tts_voice(label: str, voices: tuple[str, ...], default: str) -> str:
    print(f"  Choose a {label} voice (Enter for {default}, or type any voice name):")
    for i, name in enumerate(voices, 1):
        tag = " (default)" if name == default else ""
        print(f"    {i}. {name}{tag}")
    raw = input("  > ").strip()
    if not raw:
        return default
    try:
        idx = int(raw)
    except ValueError:
        return raw  # free-form voice name
    if 1 <= idx <= len(voices):
        return voices[idx - 1]
    return default


def _prompt_tts_config(config: ModelConfig) -> None:
    """Ask for optional spoken-reply (TTS) settings and mutate *config*."""
    print()
    print("Enable spoken replies (text-to-speech)?")
    print("  1. Skip / disable")
    print("  2. System voice — macOS `say` / Linux `espeak` (offline, no key, instant)")
    print("  3. Qwen3-TTS · cloud — via DashScope API (best quality, needs a key)")
    print("  4. Qwen3-TTS · local — runs on your own NVIDIA GPU (heavy download)")
    print("  5. Keep current TTS settings")

    while True:
        choice = input("> ").strip()
        if choice == "1":
            config.tts_provider = "disabled"
            print("  Spoken replies off. Enable later with `yumi --setup`.")
            return
        if choice == "5":
            print(f"  Keeping TTS: {config.tts_provider}")
            return
        if choice in ("2", "3", "4"):
            break
        print("Please choose one of the listed options.")

    from yumi.core.features.config.feature_install import ensure_feature_installed

    if choice == "2":
        config.tts_provider = "system"
        config.tts_voice = None
    elif choice == "3":
        config.tts_provider = "dashscope"
        config.tts_model = None
        config.tts_voice = _prompt_tts_voice("DashScope", _TTS_DASHSCOPE_VOICES, "Cherry")
        if not (config.tts_api_key or os.getenv("DASHSCOPE_API_KEY")):
            key = input("  DashScope API key (or set DASHSCOPE_API_KEY): ").strip()
            if key:
                config.tts_api_key = key
                os.environ["DASHSCOPE_API_KEY"] = key
        if not ensure_feature_installed("tts"):
            print("  The dashscope package isn't installed yet; spoken replies start once it is.")
            return
    elif choice == "4":
        import importlib.util

        # Local Qwen3-TTS runs on PyTorch. We deliberately do NOT auto-install it:
        # the CUDA build is multi-GB and version-specific, so only the user can
        # pick the right one. Bail with guidance rather than pulling a CPU-only
        # torch that would then fail on a GPU device.
        if importlib.util.find_spec("torch") is None:
            print("  Local Qwen3-TTS needs PyTorch, which can't be auto-installed here")
            print("  (the CUDA build is multi-GB and version-specific). Install it for your")
            print("  GPU from https://pytorch.org/get-started/locally/ , then re-run `yumi --setup`.")
            print("  No-setup alternatives: option 2 (System voice) or option 3 (DashScope cloud).")
            config.tts_provider = "disabled"
            return
        config.tts_provider = "qwen"
        config.tts_model = _QWEN_DEFAULT_MODEL
        config.tts_voice = _prompt_tts_voice("Qwen", _TTS_QWEN_SPEAKERS, "Ryan")
        if not ensure_feature_installed("tts-local"):
            print("  qwen-tts isn't installed yet; local spoken replies start once it is.")
            return

    _maybe_test_tts(config)


def _maybe_test_tts(config: ModelConfig) -> None:
    """Offer to synthesize + play a short line so the user hears the result now."""
    if (input("  Test it now — play a short line? (Y/n): ").strip().lower()) in ("n", "no"):
        return
    try:
        from yumi.core.features.tts.playback import speak

        speak("Hi, I'm Yumi. Spoken replies are on.", config=config)
    except Exception as exc:
        print(f"  TTS test skipped: {exc}")


# ── top-level run-mode + cloud pickers ──────────────────────────────────────

_CLOUD_PROVIDERS: tuple[tuple[str, str], ...] = (
    ("openai", "OpenAI"),
    ("claude", "Anthropic (Claude)"),
    ("gemini", "Gemini"),
    ("deepseek", "DeepSeek"),
)

_CLOUD_EMBEDDING_PROVIDERS: tuple[tuple[str, str], ...] = (
    ("openai", "OpenAI"),
    ("gemini", "Gemini"),
)

_FASTEMBED_MODELS: tuple[tuple[str, str, str], ...] = (
    (
        "Balanced multilingual",
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "~220MB",
    ),
    (
        "Higher quality multilingual",
        "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
        "~1.0GB",
    ),
    (
        "Maximum quality multilingual",
        "intfloat/multilingual-e5-large",
        "~2.24GB",
    ),
)


def _chat_config_available(config: ModelConfig) -> bool:
    if not config.chat_provider or not config.chat_model:
        return False
    from yumi.core.platform.providers import SUPPORTED_PROVIDERS

    if config.chat_provider not in SUPPORTED_PROVIDERS:
        return False
    try:
        ensure_provider_available(config.chat_provider)
    except Exception:
        return False
    return True


def _embedding_config_available(config: ModelConfig) -> bool:
    if not config.embedding_provider or config.embedding_provider == "disabled" or not config.embedding_model:
        return False
    try:
        ensure_provider_available(config.embedding_provider)
    except Exception:
        return False
    if config.embedding_provider == "ollama":
        try:
            return is_model_available(config.embedding_provider, config.embedding_model)
        except Exception:
            return False
    return True


def _choose_run_mode() -> str:
    """Return 'cloud' or 'local'. Cloud and local are presented equally."""
    print("How do you want to run the AI model?")
    print("  1. Cloud API key   — quickest start, any machine (OpenAI / Claude / Gemini / DeepSeek)")
    print("  2. Local (Ollama)  — fully private & offline; needs Ollama + a model download")
    while True:
        choice = input("> ").strip()
        if choice == "1":
            return "cloud"
        if choice == "2":
            return "local"
        print("Please enter 1 or 2.")


def _choose_chat_action(current: ModelConfig) -> str:
    if not current.chat_model:
        print("No chat model is configured yet. Choose one to continue.")
        return "reconfigure"
    if not _chat_config_available(current):
        print(f"Current chat model is configured but not available: {current.chat_provider} / {current.chat_model}")
        print("Choose a working chat model to continue.")
        return "reconfigure"

    print(f"Current chat model: {current.chat_provider} / {current.chat_model}")
    print("  1. Keep current")
    print("  2. Reconfigure")
    while True:
        choice = input("> ").strip()
        if choice in ("", "1"):
            return "keep"
        if choice == "2":
            return "reconfigure"
        print("Please enter 1 or 2.")


def _provider_label(provider: str) -> str:
    for key, label in _CLOUD_PROVIDERS:
        if key == provider:
            return label
    for key, label in _CLOUD_EMBEDDING_PROVIDERS:
        if key == provider:
            return label
    return provider


def _choose_cloud_provider() -> str | None:
    print()
    print("Which provider?")
    for i, (_key, label) in enumerate(_CLOUD_PROVIDERS, 1):
        print(f"  {i}. {label}")
    back_idx = len(_CLOUD_PROVIDERS) + 1
    print(f"  {back_idx}. Back")
    while True:
        choice = input("> ").strip()
        try:
            idx = int(choice)
        except ValueError:
            print("Please enter a valid number.")
            continue
        if idx == back_idx:
            return None
        if 1 <= idx <= len(_CLOUD_PROVIDERS):
            return _CLOUD_PROVIDERS[idx - 1][0]
        print("That selection is out of range.")


def _choose_recommended_model(provider: str, label: str) -> str | None:
    """Pick from the curated default models for a cloud provider (or custom)."""
    models = RECOMMENDED_CHAT_MODELS.get(provider, [])
    if not models:
        return _prompt_model_name(provider, label)

    print()
    print(f"Choose a {label} model:")
    for i, name in enumerate(models, 1):
        tag = "  (recommended)" if i == 1 else ""
        print(f"  {i}. {name}{tag}")
    custom_idx = len(models) + 1
    print(f"  {custom_idx}. Enter a custom model name")
    back_idx = custom_idx + 1
    print(f"  {back_idx}. Back")

    while True:
        choice = input("> ").strip()
        if not choice:
            return models[0]
        try:
            idx = int(choice)
        except ValueError:
            print("Please enter a valid number.")
            continue
        if 1 <= idx <= len(models):
            return models[idx - 1]
        if idx == custom_idx:
            name = input(f"  {label.capitalize()} model name: ").strip()
            if name:
                return name
            print("  Model name cannot be empty.")
            continue
        if idx == back_idx:
            return None
        print("That selection is out of range.")


def _ensure_chat_provider_api_key(provider: str) -> bool:
    target = _api_key_target(provider)
    if target is None:
        return True
    env_var, _field = target
    label = _provider_label(provider)
    existing = _existing_api_key(provider)
    if existing:
        use_existing = input(f"  Use existing {label} API key ({_mask_secret(existing)})? (Y/n): ").strip().lower()
        if use_existing not in ("n", "no"):
            os.environ[env_var] = existing
            return True
        key = input(f"  New {label} API key (Enter to go back): ").strip()
    else:
        key = input(f"  {label} API key (Enter to go back): ").strip()
    if not key:
        print("  A working chat provider is required to continue.")
        return False
    _persist_cloud_api_key(provider, key, announce=False)
    return True


def _configure_chat_model() -> tuple[str, str]:
    while True:
        mode = _choose_run_mode()
        if mode == "cloud":
            chat_provider = _choose_cloud_provider()
            if chat_provider is None:
                continue
            if not _ensure_chat_provider_api_key(chat_provider):
                continue
            chat_model = _choose_recommended_model(chat_provider, "chat")
            if chat_model is None:
                continue
            try:
                ensure_provider_available(chat_provider)
            except Exception as exc:
                print(f"  Chat provider '{chat_provider}' is not ready: {exc}")
                continue
            return chat_provider, chat_model

        try:
            ensure_provider_available("ollama")
        except Exception as exc:
            print()
            print("  Ollama isn't reachable. Install it from https://ollama.com and start it,")
            print(f"  or pick a cloud API key instead. Details: {exc}")
            continue
        chat_model = _prompt_model_name("ollama", "chat")
        if chat_model is None:
            continue
        return "ollama", chat_model


def _cloud_embedding_options(chat_provider: str) -> list[tuple[str, str]]:
    options = list(_CLOUD_EMBEDDING_PROVIDERS)
    if chat_provider in {key for key, _label in options}:
        options.sort(key=lambda pair: pair[0] != chat_provider)
    return options


def _ensure_cloud_embedding_key(provider: str, label: str) -> bool:
    target = _api_key_target(provider)
    if target is None:
        return False
    env_var, _field = target
    existing = _existing_api_key(provider)
    if existing:
        use_existing = input(f"  Use existing {label} API key ({_mask_secret(existing)})? (Y/n): ").strip().lower()
        if use_existing not in ("n", "no"):
            os.environ[env_var] = existing
            return True
        key = input(f"  New {label} API key (Enter to go back): ").strip()
    else:
        key = input(f"  {label} API key (Enter to go back): ").strip()
    if not key:
        print("  Back to embedding provider choices.")
        return False
    _persist_cloud_api_key(provider, key, announce=False)
    return True


def _setup_cloud_embeddings(config: ModelConfig, chat_provider: str) -> bool:
    while True:
        options = _cloud_embedding_options(chat_provider)
        print()
        print("Cloud embeddings:")
        for i, (_provider, label) in enumerate(options, 1):
            print(f"  {i}. {label}")
        back_idx = len(options) + 1
        print(f"  {back_idx}. Back")

        choice = input("> ").strip()
        try:
            idx = int(choice)
        except ValueError:
            print("Please enter a valid number.")
            continue
        if idx == back_idx:
            return False
        if not (1 <= idx <= len(options)):
            print("That selection is out of range.")
            continue

        provider, label = options[idx - 1]
        if not _ensure_cloud_embedding_key(provider, label):
            continue
        config.embedding_provider = provider
        config.embedding_model = RECOMMENDED_EMBEDDING_MODELS[provider]
        print(f"  Cloud embeddings configured with {label}.")
        return True


def _prepare_fastembed_model(model: str, size_label: str) -> bool:
    from yumi.core.features.config.feature_install import ensure_feature_installed

    print()
    print("  Installing local embedding support if needed...")
    if not ensure_feature_installed("embed", assume_yes=True):
        print("  Local embeddings are not ready. Choose another backend or retry later.")
        return False

    print(f"  Preparing local embedding model ({size_label}).")
    print("  This may take a few minutes the first time; download progress will be shown below.")
    try:
        _get_provider("fastembed").pull_model(model)
    except Exception as exc:
        print(f"  Could not prepare local embedding model: {exc}")
        return False
    print("  Local embedding model is ready.")
    return True


def _setup_fastembed_embeddings(config: ModelConfig) -> bool:
    while True:
        print()
        print("Local embeddings:")
        for i, (label, _model, size) in enumerate(_FASTEMBED_MODELS, 1):
            print(f"  {i}. {label} ({size})")
        back_idx = len(_FASTEMBED_MODELS) + 1
        print(f"  {back_idx}. Back")

        choice = input("> ").strip()
        try:
            idx = int(choice)
        except ValueError:
            print("Please enter a valid number.")
            continue
        if idx == back_idx:
            return False
        if not (1 <= idx <= len(_FASTEMBED_MODELS)):
            print("That selection is out of range.")
            continue

        _label, model, size = _FASTEMBED_MODELS[idx - 1]
        if not _prepare_fastembed_model(model, size):
            return False
        config.embedding_provider = "fastembed"
        config.embedding_model = model
        return True


def _choose_installed_ollama_embedding_model() -> str | None:
    try:
        models = _get_provider("ollama").list_models()
    except Exception as exc:
        print(f"  Could not list Ollama models: {exc}")
        return None
    if not models:
        print("  No installed Ollama models were found.")
        return None

    while True:
        print()
        print("Installed Ollama models:")
        for i, model in enumerate(models, 1):
            print(f"  {i}. {model}")
        back_idx = len(models) + 1
        print(f"  {back_idx}. Back")
        choice = input("> ").strip()
        try:
            idx = int(choice)
        except ValueError:
            print("Please enter a valid number.")
            continue
        if idx == back_idx:
            return None
        if 1 <= idx <= len(models):
            return models[idx - 1]
        print("That selection is out of range.")


def _setup_ollama_embeddings(config: ModelConfig) -> bool:
    try:
        ensure_provider_available("ollama")
    except Exception as exc:
        print()
        print("  Ollama embeddings require Ollama to be installed and running first.")
        print(f"  {exc}")
        return False

    while True:
        print()
        print("Ollama embeddings:")
        print("  1. Choose an installed Ollama model")
        print("  2. Enter a model name")
        print("  3. Back")
        choice = input("> ").strip()
        if choice == "1":
            model = _choose_installed_ollama_embedding_model()
            if not model:
                continue
            config.embedding_provider = "ollama"
            config.embedding_model = model
            return True
        if choice == "2":
            model_name = input("  Ollama embedding model name (Enter to go back): ").strip()
            if not model_name:
                continue
            try:
                model = ensure_model_ready("ollama", model_name)
            except Exception as exc:
                print(f"  Failed to prepare {model_name}: {exc}")
                continue
            config.embedding_provider = "ollama"
            config.embedding_model = model
            return True
        if choice == "3":
            return False
        print("Please choose one of the listed options.")


def _choose_embedding_action(config: ModelConfig) -> str:
    if not _embedding_config_available(config):
        if config.embedding_provider not in ("", "disabled") and config.embedding_model:
            print(
                "Current embeddings are configured but not available: "
                f"{config.embedding_provider} / {config.embedding_model}"
            )
        return "reconfigure"

    print(f"Current embeddings: {config.embedding_provider} / {config.embedding_model}")
    print("  1. Keep current")
    print("  2. Reconfigure")
    while True:
        choice = input("> ").strip()
        if choice in ("", "1"):
            return "keep"
        if choice == "2":
            return "reconfigure"
        print("Please enter 1 or 2.")


def _configure_embeddings(config: ModelConfig, chat_provider: str) -> None:
    """Embedding backend selection with backtracking submenus."""
    while True:
        print()
        print("Embeddings improve memory search and Edge tool routing.")
        print("Choose an embedding backend:")
        print("  1. Cloud embeddings")
        print("  2. Local embeddings — Yumi installs and downloads everything from the CLI")
        print("  3. Ollama embeddings — requires Ollama already installed and running")
        print("  4. Skip embeddings for now — Yumi still runs, but memory/tool routing quality will be reduced")
        choice = input("> ").strip()
        if choice == "1":
            if _setup_cloud_embeddings(config, chat_provider):
                return
            continue
        if choice == "2":
            if _setup_fastembed_embeddings(config):
                return
            continue
        if choice == "3":
            if _setup_ollama_embeddings(config):
                return
            continue
        if choice == "4":
            config.embedding_provider = "disabled"
            config.embedding_model = None
            print("  Embeddings skipped for now. Enable later with `yumi --setup`.")
            return
        print("Please choose one of the listed options.")


def _setup_embeddings(config: ModelConfig, chat_provider: str) -> None:
    action = _choose_embedding_action(config)
    if action == "keep":
        return
    _configure_embeddings(config, chat_provider)


def configure_models_noninteractive(
    *,
    provider: str,
    model: str | None = None,
    api_key: str | None = None,
    embedding_provider: str | None = None,
    embedding_model: str | None = None,
    no_embeddings: bool = False,
) -> ModelConfig:
    """Apply a model config without any prompts (for `--setup --provider ...`/CI).

    Missing ``model`` falls back to the provider's recommended default. Embeddings
    default to off unless an embedding provider/model is given.
    """
    from yumi.core.platform.providers import SUPPORTED_PROVIDERS

    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"Unknown chat provider {provider!r}. Supported: {', '.join(SUPPORTED_PROVIDERS)}")

    config = load_saved_model_config()
    config.chat_provider = provider
    config.chat_model = model or (RECOMMENDED_CHAT_MODELS.get(provider) or [None])[0]
    if not config.chat_model:
        raise ValueError(f"No model given and no recommended default for provider {provider!r}.")
    if api_key:
        # Set on this config (the single save below persists it) + process env.
        _key_fields = {
            "openai": ("OPENAI_API_KEY", "openai_api_key"),
            "gemini": ("GEMINI_API_KEY", "gemini_api_key"),
            "claude": ("ANTHROPIC_API_KEY", "claude_api_key"),
            "deepseek": ("DEEPSEEK_API_KEY", "deepseek_api_key"),
        }
        pair = _key_fields.get(provider)
        if pair:
            env_var, field = pair
            os.environ[env_var] = api_key
            setattr(config, field, api_key)

    if no_embeddings:
        config.embedding_provider = "disabled"
        config.embedding_model = None
    elif embedding_provider:
        ensure_embedding_provider_supported(embedding_provider)
        config.embedding_provider = embedding_provider
        config.embedding_model = (
            None
            if embedding_provider == "disabled"
            else embedding_model or RECOMMENDED_EMBEDDING_MODELS.get(embedding_provider)
        )
    else:
        config.embedding_provider = "disabled"
        config.embedding_model = None

    save_model_config(config)
    return config


def run_model_setup(force: bool = False) -> ModelConfig:
    current = load_saved_model_config()
    if current.chat_model and not force:
        return load_model_config()

    print("Welcome to Yumi.")
    print("Let's set you up — first choose a working chat model; the last 3 steps are optional.\n")

    print("── Step 1/4: AI model ──")
    config = load_saved_model_config()
    chat_action = _choose_chat_action(current)
    if chat_action == "keep":
        chat_provider = config.chat_provider
    else:
        chat_provider, chat_model = _configure_chat_model()
        config.chat_provider = chat_provider
        config.chat_model = chat_model
    config.system_prompt = current.system_prompt

    print("\n── Step 2/4: Memory (text embeddings) ──")
    _setup_embeddings(config, chat_provider)
    print("\n── Step 3/4: Voice input (speech-to-text) ──")
    _prompt_stt_config(config)
    print("\n── Step 4/4: Spoken replies (text-to-speech) ──")
    _prompt_tts_config(config)
    save_model_config(config)

    print()
    print(f"Saved Yumi model config to {CONFIG_PATH}.")
    print(f"Chat: {config.chat_provider} / {config.chat_model}")
    emb = f"{config.embedding_provider} / {config.embedding_model}" if config.embedding_model else "off"
    print(f"Embedding: {emb}")
    print(f"STT: {config.stt_provider} / {config.stt_model or 'disabled'}")
    tts = config.tts_provider if config.tts_provider not in ("", "disabled") else "off"
    if config.tts_voice and tts != "off":
        tts = f"{tts} / {config.tts_voice}"
    print(f"TTS: {tts}")
    return config
