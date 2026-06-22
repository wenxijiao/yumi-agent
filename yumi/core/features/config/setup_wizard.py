"""Interactive terminal wizard for chat/embedding model selection."""

import os
import shutil
import sys
import textwrap

from yumi.core.features.config.credentials import (
    _get_provider,
    ensure_embedding_provider_supported,
    ensure_model_ready,
    ensure_provider_available,
    get_api_credentials,
    is_model_available,
)
from yumi.core.features.config.model import (
    RECOMMENDED_CHAT_MODELS,
    RECOMMENDED_EMBEDDING_MODELS,
    ModelConfig,
)
from yumi.core.features.config.paths import CONFIG_DIR, CONFIG_PATH
from yumi.core.features.config.store import load_model_config, load_saved_model_config, save_model_config


def _interactive_terminal() -> bool:
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


def _clear_screen() -> None:
    if not _interactive_terminal():
        return
    os.system("cls" if os.name == "nt" else "clear")


def _red(text: str) -> str:
    if not _interactive_terminal() or os.getenv("NO_COLOR"):
        return text
    return f"\033[31m{text}\033[0m"


def _yellow(text: str) -> str:
    if not _interactive_terminal() or os.getenv("NO_COLOR"):
        return text
    return f"\033[33m{text}\033[0m"


_SELECT_TEXT_PAD = "   "


def _select_wrap_width(prefix: str) -> int:
    columns = shutil.get_terminal_size((100, 24)).columns
    return max(20, columns - len(prefix) - 1)


def _wrapped_select_lines(text: str, *, prefix: str) -> list[str]:
    lines: list[str] = []
    for raw in text.splitlines() or [""]:
        wrapped = textwrap.wrap(
            raw,
            width=_select_wrap_width(prefix),
            break_long_words=False,
            break_on_hyphens=False,
        )
        lines.extend(wrapped or [""])
    return lines


def _print_select_text(text: str = "", *, style=None) -> None:
    if not text:
        print()
        return
    for line in _wrapped_select_lines(text, prefix=_SELECT_TEXT_PAD):
        print(f"{_SELECT_TEXT_PAD}{style(line) if style else line}")


def _print_select_option(marker: str, text: str) -> None:
    first_prefix = f" {marker} "
    for index, line in enumerate(_wrapped_select_lines(text, prefix=first_prefix)):
        prefix = first_prefix if index == 0 else _SELECT_TEXT_PAD
        print(f"{prefix}{line}")


def _read_key() -> str:
    """Read one navigation key from an interactive terminal."""
    if os.name == "nt":
        import msvcrt

        ch = msvcrt.getwch()
        if ch == "\x03":
            raise KeyboardInterrupt
        if ch in ("\x00", "\xe0"):
            code = msvcrt.getwch()
            if code == "H":
                return "up"
            if code == "P":
                return "down"
            return ""
        if ch in ("\r", "\n"):
            return "enter"
        return ch

    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x03":
            raise KeyboardInterrupt
        if ch in ("\r", "\n"):
            return "enter"
        if ch == "\x1b":
            seq = sys.stdin.read(2)
            if seq == "[A":
                return "up"
            if seq == "[B":
                return "down"
            return ""
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _draw_select_page(
    *,
    step: str | None,
    title: str,
    options: list[tuple[str, str, str]],
    selected: int,
    message: str | None = None,
    warning: str | None = None,
    error: str | None = None,
    footer: str | None = None,
) -> None:
    _clear_screen()
    _print_select_text("Yumi setup")
    if step:
        _print_select_text(step)
    print()
    _print_select_text(title)
    if message:
        _print_select_text(message)
    if warning:
        print()
        _print_select_text(warning, style=_yellow)
    if error:
        print()
        _print_select_text(error, style=_red)
    print()
    label_width = max((len(label) for _value, label, _description in options), default=0)
    for index, (_value, label, description) in enumerate(options):
        marker = ">" if index == selected else " "
        if description:
            _print_select_option(marker, f"{label:<{label_width}} — {description}")
        else:
            _print_select_option(marker, label)
    print()
    _print_select_text(footer or "Use ↑/↓ to move. Press Enter to confirm.")


def _select_option(
    *,
    title: str,
    options: list[tuple[str, str, str]],
    step: str | None = None,
    message: str | None = None,
    warning: str | None = None,
    error: str | None = None,
    footer: str | None = None,
    default: int = 0,
) -> str:
    """Select an option with arrow keys on a TTY, numeric input otherwise."""
    if not options:
        raise ValueError("options cannot be empty")

    if not _interactive_terminal():
        if step:
            print(step)
        print(title)
        if message:
            print(message)
        if warning:
            print(warning)
        if error:
            print(error)
        for i, (_value, label, description) in enumerate(options, 1):
            suffix = f" — {description}" if description else ""
            print(f"  {i}. {label}{suffix}")
        while True:
            choice = input("> ").strip()
            if not choice:
                return options[min(max(default, 0), len(options) - 1)][0]
            try:
                idx = int(choice)
            except ValueError:
                print(f"Please enter a number from 1 to {len(options)}.")
                continue
            if 1 <= idx <= len(options):
                return options[idx - 1][0]
            print("That selection is out of range.")

    selected = min(max(default, 0), len(options) - 1)
    while True:
        _draw_select_page(
            step=step,
            title=title,
            message=message,
            warning=warning,
            error=error,
            options=options,
            selected=selected,
            footer=footer,
        )
        key = _read_key()
        if key == "up":
            selected = (selected - 1) % len(options)
        elif key == "down":
            selected = (selected + 1) % len(options)
        elif key == "enter":
            return options[selected][0]
        elif key.isdigit():
            idx = int(key)
            if 1 <= idx <= len(options):
                return options[idx - 1][0]


def _api_key_target(provider_name: str) -> tuple[str, str] | None:
    if provider_name == "openai":
        return "OPENAI_API_KEY", "openai_api_key"
    if provider_name == "gemini":
        return "GEMINI_API_KEY", "gemini_api_key"
    if provider_name == "claude":
        return "ANTHROPIC_API_KEY", "claude_api_key"
    if provider_name == "deepseek":
        return "DEEPSEEK_API_KEY", "deepseek_api_key"
    if provider_name == "grok":
        return "XAI_API_KEY", "grok_api_key"
    return None


def _existing_api_key(provider_name: str) -> str | None:
    target = _api_key_target(provider_name)
    if target is None:
        return None
    _env_var, field = target
    return get_api_credentials().get(field)


def _mask_secret(value: str) -> str:
    return value[:4] + "..." + value[-4:] if len(value) > 8 else "***"


def _choose_installed_model(models: list[str], label: str, *, step: str | None = None) -> str | None:
    options = [(model, model, "") for model in models]
    options.append(("back", "Back", ""))
    selected = _select_option(
        step=step,
        title=f"Choose an installed {label} model",
        options=options,
    )
    return None if selected == "back" else selected


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
        options: list[tuple[str, str, str]] = []
        if installed:
            options.append(("installed", f"Use an installed {label} model", ""))
        rec = (RECOMMENDED_CHAT_MODELS.get("ollama") or [None])[0] if label == "chat" else None
        options.extend(
            [
                *([("default", f"Download default {label} model", rec)] if rec else []),
                ("manual", f"Enter a {label} model name", "downloads it if missing"),
                ("back", "Back", ""),
            ]
        )

        action = _select_option(
            step="Step 1/5: AI model",
            title=f"Choose a {label} model",
            options=options,
        )

        if action == "installed":
            model = _choose_installed_model(installed, label, step="Step 1/5: AI model")
            if model:
                return model
            continue

        if action == "default" and rec:
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
_DEFAULT_WHISPER_MODEL_DIR = CONFIG_DIR / "models" / "whisper"


def _prompt_stt_config(config: ModelConfig) -> None:
    """Ask for optional local STT settings and mutate *config*."""
    choice = _select_option(
        step="Step 3/5: Voice input (speech-to-text)",
        title="Configure speech-to-text (STT) for voice messages?",
        options=[
            ("keep", "Keep existing STT settings", ""),
            ("whisper", "Use local Whisper multilingual model", ""),
            ("disable", "Skip / disable STT", ""),
        ],
    )
    if choice == "disable":
        config.stt_provider = "disabled"
        config.stt_backend = "faster-whisper"
        config.stt_model = None
        config.stt_language = "auto"
        print("  STT disabled. You can enable it later with `yumi --setup`.")
        return
    if choice == "keep":
        print(f"  Keeping STT: {config.stt_provider} / {config.stt_model or 'unset'}")
        return

    model = _select_option(
        step="Step 3/5: Voice input (speech-to-text)",
        title="Choose a Whisper multilingual model",
        options=[(name, name, "") for name in _WHISPER_MODELS],
    )

    config.stt_provider = "whisper"
    config.stt_backend = "faster-whisper"
    config.stt_model = model
    config.stt_model_dir = str(_DEFAULT_WHISPER_MODEL_DIR)
    config.stt_language = "auto"

    from yumi.core.features.config.feature_install import ensure_feature_installed

    if not ensure_feature_installed("stt", assume_yes=True):
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


def _prompt_tts_voice(label: str, voices: tuple[str, ...], default: str) -> str:
    options = [(name, name, "default" if name == default else "") for name in voices]
    options.append(("custom", "Enter a custom voice name", ""))
    selected = _select_option(
        step="Step 4/5: Spoken replies (text-to-speech)",
        title=f"Choose a {label} voice",
        options=options,
        default=voices.index(default) if default in voices else 0,
    )
    if selected == "custom":
        custom = input("  Voice name (Enter for default): ").strip()
        return custom or default
    if not selected:
        return default
    return selected


def _prompt_tts_config(config: ModelConfig) -> None:
    """Ask for optional spoken-reply (TTS) settings and mutate *config*."""
    choice = _select_option(
        step="Step 4/5: Spoken replies (text-to-speech)",
        title="Enable spoken replies (text-to-speech)?",
        options=[
            ("keep", "Keep current TTS settings", ""),
            ("system", "System voice", "macOS say / Linux espeak; offline, no key, instant"),
            ("dashscope", "Qwen3-TTS cloud", "via DashScope API; best quality; needs a key"),
            ("disable", "Skip / disable", ""),
        ],
    )
    if choice == "disable":
        config.tts_provider = "disabled"
        print("  Spoken replies off. Enable later with `yumi --setup`.")
        return
    if choice == "keep":
        print(f"  Keeping TTS: {config.tts_provider}")
        return

    from yumi.core.features.config.feature_install import ensure_feature_installed

    if choice == "system":
        config.tts_provider = "system"
        config.tts_voice = None
    elif choice == "dashscope":
        config.tts_provider = "dashscope"
        config.tts_model = None
        config.tts_voice = _prompt_tts_voice("DashScope", _TTS_DASHSCOPE_VOICES, "Cherry")
        if not (config.tts_api_key or os.getenv("DASHSCOPE_API_KEY")):
            key = input("  DashScope API key (or set DASHSCOPE_API_KEY): ").strip()
            if key:
                config.tts_api_key = key
                os.environ["DASHSCOPE_API_KEY"] = key
        if not ensure_feature_installed("tts", assume_yes=True):
            print("  The dashscope package isn't installed yet; spoken replies start once it is.")
            return


# ── top-level run-mode + cloud pickers ──────────────────────────────────────

_CLOUD_PROVIDERS: tuple[tuple[str, str], ...] = (
    ("openai", "OpenAI"),
    ("claude", "Anthropic (Claude)"),
    ("gemini", "Gemini"),
    ("deepseek", "DeepSeek"),
    ("grok", "Grok (xAI)"),
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

_EMBEDDING_STABILITY_WARNING = (
    "Important: keep the same embedding provider/model once Yumi starts saving memory.\n"
    "Changing it later can make old memory and tool-routing vectors inconsistent; "
    "run `yumi --cleanup-memory` first if you need to switch."
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


def _choose_run_mode(notice: str | None = None) -> str:
    """Return 'cloud' or 'local'. Cloud and local are presented equally."""
    return _select_option(
        step="Step 1/5: AI model",
        title="How do you want to run the AI model?",
        message="No chat model is configured yet. Choose one to continue.",
        error=notice,
        options=[
            ("cloud", "Cloud API key", "quickest start, any machine (OpenAI / Claude / Gemini / DeepSeek / Grok)"),
            ("local", "Local (Ollama)", "fully private and offline; needs Ollama running"),
            ("exit", "Exit setup", ""),
        ],
    )


def _choose_chat_action(current: ModelConfig) -> str:
    if not current.chat_model:
        print("No chat model is configured yet. Choose one to continue.")
        return "reconfigure"
    if not _chat_config_available(current):
        print(f"Current chat model is configured but not available: {current.chat_provider} / {current.chat_model}")
        print("Choose a working chat model to continue.")
        return "reconfigure"

    return _select_option(
        step="Step 1/5: AI model",
        title="Current chat model is configured.",
        message=f"{current.chat_provider} / {current.chat_model}",
        options=[
            ("keep", "Keep current", ""),
            ("reconfigure", "Reconfigure", ""),
        ],
    )


def _provider_label(provider: str) -> str:
    for key, label in _CLOUD_PROVIDERS:
        if key == provider:
            return label
    for key, label in _CLOUD_EMBEDDING_PROVIDERS:
        if key == provider:
            return label
    return provider


def _choose_cloud_provider() -> str | None:
    options = [(key, label, "") for key, label in _CLOUD_PROVIDERS]
    options.append(("back", "Back", ""))
    selected = _select_option(
        step="Step 1/5: AI model",
        title="Which cloud provider do you want to use?",
        options=options,
    )
    return None if selected == "back" else selected


def _choose_cloud_model(provider: str, label: str) -> str | None:
    """Let users quickly pick known model ids, or enter their own."""
    models = RECOMMENDED_CHAT_MODELS.get(provider, [])
    if not models:
        return _prompt_model_name(provider, label)

    while True:
        options = [(name, name, "") for name in models]
        options.append(("custom", "Enter a custom model name", ""))
        options.append(("back", "Back", ""))
        selected = _select_option(
            step="Step 1/5: AI model",
            title=f"Choose a {label} model for {_provider_label(provider)}",
            options=options,
        )
        if selected in models:
            return selected
        if selected == "custom":
            name = input(f"  {label.capitalize()} model name: ").strip()
            if name:
                return name
            print("  Model name cannot be empty.")
            continue
        if selected == "back":
            return None


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
    notice: str | None = None
    while True:
        mode = _choose_run_mode(notice)
        notice = None
        if mode == "exit":
            raise SystemExit("  Setup cancelled.")
        if mode == "cloud":
            chat_provider = _choose_cloud_provider()
            if chat_provider is None:
                continue
            if not _ensure_chat_provider_api_key(chat_provider):
                continue
            chat_model = _choose_cloud_model(chat_provider, "chat")
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
            notice = (
                "Ollama isn't reachable. Install it from https://ollama.com and start it, "
                f"or pick a cloud API key instead.\nDetails: {exc}"
            )
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
        return False
    _persist_cloud_api_key(provider, key, announce=False)
    return True


def _setup_cloud_embeddings(config: ModelConfig, chat_provider: str) -> bool:
    while True:
        options = [(provider, label, "") for provider, label in _cloud_embedding_options(chat_provider)]
        options.append(("back", "Back", ""))
        provider = _select_option(
            step="Step 2/5: Memory (text embeddings)",
            title="Choose a cloud embedding provider",
            options=options,
        )
        if provider == "back":
            return False

        label = _provider_label(provider)
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
        options = [(model, label, size) for label, model, size in _FASTEMBED_MODELS]
        options.append(("back", "Back", ""))
        selected = _select_option(
            step="Step 2/5: Memory (text embeddings)",
            title="Choose a local embedding model",
            options=options,
        )
        if selected == "back":
            return False

        model = selected
        size = next(size for _label, candidate, size in _FASTEMBED_MODELS if candidate == model)
        if not _prepare_fastembed_model(model, size):
            return False
        config.embedding_provider = "fastembed"
        config.embedding_model = model
        _clear_screen()
        return True


def _setup_ollama_embeddings(config: ModelConfig) -> bool:
    notice: str | None = None
    try:
        ensure_provider_available("ollama")
    except Exception as exc:
        notice = f"Ollama embeddings require Ollama to be installed and running first.\nDetails: {exc}"

    while True:
        choice = _select_option(
            step="Step 2/5: Memory (text embeddings)",
            title="Configure Ollama embeddings",
            error=notice,
            options=[
                ("installed", "Choose an installed Ollama model", ""),
                ("manual", "Enter a model name", ""),
                ("back", "Back", ""),
            ],
        )
        notice = None
        if choice == "installed":
            try:
                models = _get_provider("ollama").list_models()
            except Exception as exc:
                notice = f"Could not list installed Ollama models.\nDetails: {exc}"
                continue
            if not models:
                notice = (
                    "No installed Ollama embedding models were found.\n"
                    "Choose 'Enter a model name' to download one, or run `ollama pull qwen3-embedding:0.6b` first."
                )
                continue
            model = _choose_installed_model(models, "Ollama embedding", step="Step 2/5: Memory (text embeddings)")
            if not model:
                continue
            config.embedding_provider = "ollama"
            config.embedding_model = model
            return True
        if choice == "manual":
            model_name = input("  Ollama embedding model name (Enter to go back): ").strip()
            if not model_name:
                continue
            try:
                model = ensure_model_ready("ollama", model_name)
            except Exception as exc:
                notice = f"Failed to prepare Ollama embedding model {model_name!r}.\nDetails: {exc}"
                continue
            config.embedding_provider = "ollama"
            config.embedding_model = model
            _clear_screen()
            return True
        if choice == "back":
            return False


def _choose_embedding_action(config: ModelConfig) -> str:
    if not _embedding_config_available(config):
        if config.embedding_provider not in ("", "disabled") and config.embedding_model:
            print(
                "Current embeddings are configured but not available: "
                f"{config.embedding_provider} / {config.embedding_model}"
            )
        return "reconfigure"

    return _select_option(
        step="Step 2/5: Memory (text embeddings)",
        title="Current embeddings are configured.",
        message=f"{config.embedding_provider} / {config.embedding_model}",
        warning=_EMBEDDING_STABILITY_WARNING,
        options=[
            ("keep", "Keep current", ""),
            ("reconfigure", "Reconfigure", ""),
        ],
    )


def _configure_embeddings(config: ModelConfig, chat_provider: str) -> None:
    """Embedding backend selection with backtracking submenus."""
    while True:
        choice = _select_option(
            step="Step 2/5: Memory (text embeddings)",
            title="Choose an embedding backend",
            message="Embeddings improve memory search and Edge tool routing.",
            warning=_EMBEDDING_STABILITY_WARNING,
            options=[
                ("cloud", "Cloud embeddings", ""),
                ("local", "Local embeddings", "Yumi installs and downloads everything from the CLI"),
                ("ollama", "Ollama embeddings", "requires Ollama already installed and running"),
                ("skip", "Skip embeddings for now", "memory and tool-routing quality will be reduced"),
            ],
        )
        if choice == "cloud":
            if _setup_cloud_embeddings(config, chat_provider):
                return
            continue
        if choice == "local":
            if _setup_fastembed_embeddings(config):
                return
            continue
        if choice == "ollama":
            if _setup_ollama_embeddings(config):
                return
            continue
        if choice == "skip":
            config.embedding_provider = "disabled"
            config.embedding_model = None
            print("  Embeddings skipped for now. Enable later with `yumi --setup`.")
            return


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

    Missing ``model`` falls back to the provider's non-interactive default. Embeddings
    default to off unless an embedding provider/model is given.
    """
    from yumi.core.platform.providers import SUPPORTED_PROVIDERS

    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(f"Unknown chat provider {provider!r}. Supported: {', '.join(SUPPORTED_PROVIDERS)}")

    config = load_saved_model_config()
    config.chat_provider = provider
    config.chat_model = model or (RECOMMENDED_CHAT_MODELS.get(provider) or [None])[0]
    if not config.chat_model:
        raise ValueError(f"No model given and no non-interactive default for provider {provider!r}.")
    if api_key:
        # Set on this config (the single save below persists it) + process env.
        _key_fields = {
            "openai": ("OPENAI_API_KEY", "openai_api_key"),
            "gemini": ("GEMINI_API_KEY", "gemini_api_key"),
            "claude": ("ANTHROPIC_API_KEY", "claude_api_key"),
            "deepseek": ("DEEPSEEK_API_KEY", "deepseek_api_key"),
            "grok": ("XAI_API_KEY", "grok_api_key"),
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

    if not _interactive_terminal():
        print("Welcome to Yumi.")
        print("Let's set you up — first choose a working chat model; the remaining steps are optional.\n")

    if not _interactive_terminal():
        print("── Step 1/5: AI model ──")
    config = load_saved_model_config()
    chat_action = _choose_chat_action(current)
    if chat_action == "keep":
        chat_provider = config.chat_provider
    else:
        chat_provider, chat_model = _configure_chat_model()
        config.chat_provider = chat_provider
        config.chat_model = chat_model
    config.system_prompt = current.system_prompt
    save_model_config(config)

    if not _interactive_terminal():
        print("\n── Step 2/5: Memory (text embeddings) ──")
    _setup_embeddings(config, chat_provider)
    save_model_config(config)
    if not _interactive_terminal():
        print("\n── Step 3/5: Voice input (speech-to-text) ──")
    _prompt_stt_config(config)
    save_model_config(config)
    if not _interactive_terminal():
        print("\n── Step 4/5: Spoken replies (text-to-speech) ──")
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
