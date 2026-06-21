"""Interactive terminal wizard for chat/embedding model selection."""

import os

from yumi.core.features.config.credentials import (
    _get_provider,
    ensure_model_ready,
    ensure_provider_available,
    get_api_credentials,
)
from yumi.core.features.config.model import (
    EMBEDDING_CAPABLE_PROVIDERS,
    RECOMMENDED_CHAT_MODEL,
    RECOMMENDED_CHAT_MODELS,
    RECOMMENDED_EMBEDDING_MODEL,
    RECOMMENDED_EMBEDDING_MODELS,
    RECOMMENDED_STT_MODEL,
    ModelConfig,
)
from yumi.core.features.config.paths import CONFIG_PATH
from yumi.core.features.config.store import load_model_config, load_saved_model_config, save_model_config


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
    """Prompt for API key and save to ~/.yumi/config.json."""
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
        config.tts_provider = "qwen"
        config.tts_model = _QWEN_DEFAULT_MODEL
        config.tts_voice = _prompt_tts_voice("Qwen", _TTS_QWEN_SPEAKERS, "Ryan")
        if not ensure_feature_installed("tts-local"):
            print("  qwen-tts isn't installed yet; local spoken replies start once it is (needs a CUDA GPU).")
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


def _choose_run_mode() -> str:
    """Return 'cloud', 'local', or 'skip'. Cloud and local are presented equally."""
    print("How do you want to run the AI model?")
    print("  1. Cloud API key   — quickest start, any machine (OpenAI / Claude / Gemini / DeepSeek)")
    print("  2. Local (Ollama)  — fully private & offline; needs Ollama + a model download")
    print("  3. Skip for now    — set up later with `yumi --setup` or env vars")
    while True:
        choice = input("> ").strip()
        if choice == "1":
            return "cloud"
        if choice == "2":
            return "local"
        if choice == "3":
            return "skip"
        print("Please enter 1, 2, or 3.")


def _choose_cloud_provider() -> str:
    print()
    print("Which provider?")
    for i, (_key, label) in enumerate(_CLOUD_PROVIDERS, 1):
        print(f"  {i}. {label}")
    while True:
        choice = input("> ").strip()
        try:
            idx = int(choice)
        except ValueError:
            print("Please enter a valid number.")
            continue
        if 1 <= idx <= len(_CLOUD_PROVIDERS):
            return _CLOUD_PROVIDERS[idx - 1][0]
        print("That selection is out of range.")


def _choose_recommended_model(provider: str, label: str) -> str:
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
        print("That selection is out of range.")


def _setup_embeddings(config: ModelConfig, chat_provider: str) -> None:
    """Smart-default embedding selection. Enter accepts the recommended option."""
    creds = get_api_credentials()
    options: list[tuple[str, str, str]] = []  # (label, provider, model)
    seen: set[str] = set()

    def add(provider: str, suffix: str = "") -> None:
        model = RECOMMENDED_EMBEDDING_MODELS.get(provider)
        if not model or provider in seen:
            return
        seen.add(provider)
        options.append((f"Use {provider} embeddings ({model}){suffix}", provider, model))

    # Smartest first: reuse the chat provider when it can embed.
    if chat_provider in EMBEDDING_CAPABLE_PROVIDERS:
        add(chat_provider)
    # Local Ollama is always a candidate.
    add("ollama", "" if chat_provider == "ollama" else " — local, needs Ollama")
    # Cloud embedders the user already has a key for.
    if creds.get("openai_api_key"):
        add("openai")
    if creds.get("gemini_api_key"):
        add("gemini")

    print()
    print("Long-term memory & smart tool-search use text embeddings. Enable?")
    for i, (label, _p, _m) in enumerate(options, 1):
        tag = "  (recommended)" if i == 1 else ""
        print(f"  {i}. {label}{tag}")
    off_idx = len(options) + 1
    print(f"  {off_idx}. No — skip (cross-session memory + dynamic tool routing stay off)")

    while True:
        choice = input("> ").strip()
        sel = 1 if not choice else None
        if sel is None:
            try:
                sel = int(choice)
            except ValueError:
                print("Please enter a valid number.")
                continue
        if 1 <= sel <= len(options):
            _label, provider, model = options[sel - 1]
            if provider != "ollama" and provider != chat_provider:
                _prompt_api_key(provider, announce_save=False)
            if provider == "ollama" and chat_provider != "ollama":
                try:
                    ensure_provider_available("ollama")
                except Exception:
                    print("  Warning: Ollama not reachable yet; embeddings activate once it's running.")
            config.embedding_provider = provider
            config.embedding_model = model
            return
        if sel == off_idx:
            config.embedding_provider = "disabled"
            config.embedding_model = None
            print("  Embeddings off. Enable later with `yumi --setup`.")
            return
        print("That selection is out of range.")


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
        config.embedding_provider = embedding_provider
        config.embedding_model = embedding_model or RECOMMENDED_EMBEDDING_MODELS.get(embedding_provider)
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
    print("Let's set up the AI model.\n")
    if current.chat_model:
        print(f"Current: chat={current.chat_provider}/{current.chat_model}\n")

    mode = _choose_run_mode()
    if mode == "skip":
        print("\nSkipped. Configure later with `yumi --setup`, `YUMI_CHAT_MODEL`, or a cloud API key.")
        return load_model_config()

    if mode == "cloud":
        chat_provider = _choose_cloud_provider()
        _prompt_api_key(chat_provider, announce_save=False)
        chat_model = _choose_recommended_model(chat_provider, "chat")
    else:  # local
        chat_provider = "ollama"
        try:
            ensure_provider_available("ollama")
        except Exception:
            print("\n  Warning: Ollama isn't reachable. Install it from https://ollama.com and start it,")
            print("  then re-run `yumi --setup` (or pick a cloud API key instead).")
        chat_model = _prompt_model_name("ollama", "chat")

    config = load_saved_model_config()
    config.chat_provider = chat_provider
    config.chat_model = chat_model
    config.system_prompt = current.system_prompt

    _setup_embeddings(config, chat_provider)
    _prompt_stt_config(config)
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
