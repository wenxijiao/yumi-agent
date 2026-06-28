"""Interactive terminal wizard for chat/embedding model selection."""

import contextlib
import os
import shutil
import sys
import textwrap
from collections.abc import Callable

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


_ALT_DEPTH = 0


@contextlib.contextmanager
def _alt_screen():
    """Run an interactive flow on the terminal's alternate screen buffer.

    Like ``vim``/``less``/``claude``: the wizard draws on a separate buffer and
    the original terminal contents (scrollback) are restored on exit, so the
    menus — whether cancelled or completed — don't litter the prompt. The final
    summary is rendered *after* this context so it persists in normal
    scrollback. No-op off an interactive TTY (pipes, CI, tests).
    """
    global _ALT_DEPTH
    if not _interactive_terminal():
        yield
        return
    sys.stdout.write("\033[?1049h")  # enter alternate screen
    sys.stdout.flush()
    _ALT_DEPTH += 1
    try:
        yield
    finally:
        _ALT_DEPTH -= 1
        sys.stdout.write("\033[?1049l")  # restore the original screen
        sys.stdout.flush()


@contextlib.contextmanager
def _normal_screen():
    """Temporarily drop back to the normal screen for a noisy operation.

    Heavy work with its own output — model downloads (tqdm progress bars), pip
    installs — must not write onto the wizard's alternate-screen buffer, where
    a late/threaded flush can land *after* the next redraw and stick to the
    bottom. This leaves the alternate screen, runs the work on the normal
    terminal (where a progress bar belongs), then restores the wizard. No-op if
    we aren't currently on the alternate screen.
    """
    if _ALT_DEPTH <= 0 or not _interactive_terminal():
        yield
        return
    sys.stdout.write("\033[?1049l")  # back to the normal screen
    sys.stdout.flush()
    try:
        yield
    finally:
        sys.stdout.write("\033[?1049h")  # re-enter the (cleared) alternate screen
        sys.stdout.flush()


def _red(text: str) -> str:
    return _ansi("31", text)


def _yellow(text: str) -> str:
    return _ansi("33", text)


def _green(text: str) -> str:
    return _ansi("32", text)


def _cyan(text: str) -> str:
    return _ansi("36", text)


def _bold_cyan(text: str) -> str:
    return _ansi("1;36", text)


def _bold(text: str) -> str:
    return _ansi("1", text)


def _dim(text: str) -> str:
    return _ansi("2", text)


def _ansi(code: str, text: str) -> str:
    if not _interactive_terminal() or os.getenv("NO_COLOR"):
        return text
    return f"\033[{code}m{text}\033[0m"


_SELECT_TEXT_PAD = "  "  # the single left gutter (column 2) that every line shares
_DESC_INDENT = "    "  # option descriptions and wrapped detail hang at column 4
_SELECT_FRAME_MAX_WIDTH = 88


def _page_width() -> int:
    columns = shutil.get_terminal_size((100, 24)).columns
    return min(_SELECT_FRAME_MAX_WIDTH, max(52, columns - 6))


def _select_wrap_width(prefix: str) -> int:
    columns = shutil.get_terminal_size((100, 24)).columns
    return max(20, min(columns - len(prefix) - 1, _page_width() - len(prefix) - 1))


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


def _parse_step(step: str | None) -> tuple[int | None, int | None, str | None, str | None]:
    """Return (current, total, name, sub) from a 'Step N/M: Name · Sub' label."""
    if not step:
        return None, None, None, None
    prefix, _sep, rest = step.partition(":")
    name, _s, sub = rest.partition("·")
    name = name.strip() or None
    sub = sub.strip() or None
    if not prefix.startswith("Step "):
        return None, None, name or step, sub
    count = prefix.removeprefix("Step ").strip()
    current_text, sep, total_text = count.partition("/")
    if not sep:
        return None, None, name or step, sub
    try:
        return int(current_text), int(total_text), name or step, sub
    except ValueError:
        return None, None, name or step, sub


def _dot_rail(current: int | None, total: int | None) -> str:
    """A calm '● ● ○ ○ ○' progress rail: one dot per top-level step."""
    if not current or not total or total <= 0:
        return ""
    return " ".join(_cyan("●") if i <= current else _dim("○") for i in range(1, total + 1))


def _draw_setup_header(step: str | None) -> None:
    """One quiet rail line + a dim hairline — no box, no fuel gauge."""
    width = _page_width()
    current, total, name, sub = _parse_step(step)
    rail = _dot_rail(current, total)
    if current is not None and total is not None:
        crumb = f"Step {current} of {total}"
        if name:
            crumb += f" · {name}"
        if sub:
            crumb += f" · {sub}"
        head = f"{rail}   {_dim(crumb)}"
    elif name:
        head = _bold(name)
    else:
        head = _bold("Yumi setup")
    print(f"{_SELECT_TEXT_PAD}{head}")
    print(f"{_SELECT_TEXT_PAD}{_dim('─' * (width - 2))}")


def _print_select_option(selected: bool, label: str, description: str) -> None:
    bar = f"{_cyan('▌')} " if selected else "  "
    for index, line in enumerate(_wrapped_select_lines(label, prefix="  ")):
        prefix = bar if index == 0 else "  "
        print(f"{prefix}{_bold_cyan(line) if selected else line}")
    if description:
        for line in _wrapped_select_lines(description, prefix=_DESC_INDENT):
            print(f"{_DESC_INDENT}{_dim(line)}")


def _print_select_notice(kind: str, text: str, *, color) -> None:
    """A hanging marginal note ('! Warning' + a '│' tick-bar), never a box."""
    if not text:
        return
    print()
    print(f"{_SELECT_TEXT_PAD}{color('! ' + kind)}")
    for line in _wrapped_select_lines(text, prefix="    "):
        print(f"{_SELECT_TEXT_PAD}{color('│')} {line}")


# Success notes are queued here and rendered on the NEXT drawn screen (under the
# header) instead of being print()'d and then wiped by the following clear.
_PENDING_NOTES: list[tuple[str, bool]] = []


def _note(message: str, *, ok: bool = True) -> None:
    """Queue a one-line note to surface on the next screen (✓ ok / ! warning)."""
    _PENDING_NOTES.append((message, ok))


def _flush_notes() -> None:
    if not _PENDING_NOTES:
        return
    for message, ok in _PENDING_NOTES:
        glyph = _green("✓") if ok else _yellow("!")
        print(f"{_SELECT_TEXT_PAD}{glyph} {_dim(message)}")
    print()
    _PENDING_NOTES.clear()


def _framed_prompt(
    label: str,
    *,
    step: str | None = None,
    title: str | None = None,
    context: str | None = None,
    hint: str | None = None,
    secret: bool = False,
) -> str:
    """Read one line on a wizard-styled screen so input never appears naked.

    With ``secret=True`` the entry is masked — one ``•`` per character, so a
    pasted key is visibly received without printing the secret. Off an
    interactive TTY (pipes, CI, tests) it falls back to a single plain
    ``input()`` call, preserving the prompt-count/order the non-interactive
    flow relies on.
    """
    if not _interactive_terminal():
        try:
            return input(f"{label}: ").strip()
        except EOFError:
            # Piped/closed stdin (CI, Docker without a TTY, `yumi --setup </dev/null`):
            # cancel cleanly instead of dumping a traceback or looping forever.
            raise SystemExit("  Setup cancelled.")
    _clear_screen()
    if step:
        _draw_setup_header(step)
    print()
    _flush_notes()
    if title:
        _print_select_text(title, style=_bold)
    if context:
        _print_select_text(context, style=_dim)
    if hint:
        print()
        _print_select_text(hint, style=_dim)
    print()
    caret = f"{_SELECT_TEXT_PAD}{_cyan('▌')} {_bold(label)}: "
    if secret:
        return _read_secret(caret)
    return input(caret).strip()


def _read_key() -> str:
    """Read one navigation key from an interactive terminal."""
    if os.name == "nt":
        import msvcrt

        ch = msvcrt.getwch()
        if ch == "":
            raise EOFError  # stdin closed (EOF)
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
        if ch == "":
            raise EOFError  # stdin closed — don't spin redrawing on an empty key
        if ch == "\x03":
            raise KeyboardInterrupt
        if ch in ("\r", "\n"):
            return "enter"
        if ch == "\x1b":
            seq = sys.stdin.read(2)
            if len(seq) < 2:
                raise EOFError
            if seq == "[A":
                return "up"
            if seq == "[B":
                return "down"
            return ""
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _read_secret(prompt: str) -> str:
    """Read a secret, echoing one ``•`` per character so paste/typing is visible.

    Unlike ``getpass`` (which shows nothing), this confirms input is landing —
    you can see the field fill as you paste — without printing the secret. Off
    an interactive TTY it falls back to a plain ``input()``.
    """
    if not _interactive_terminal():
        return input(prompt).strip()

    chars: list[str] = []

    if os.name == "nt":
        import msvcrt

        sys.stdout.write(prompt)
        sys.stdout.flush()
        while True:
            ch = msvcrt.getwch()
            if ch in ("\r", "\n"):
                break
            if ch == "\x03":
                raise KeyboardInterrupt
            if ch == "\x08":  # backspace
                if chars:
                    chars.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
                continue
            if ch.isprintable():
                chars.append(ch)
                sys.stdout.write("•")
                sys.stdout.flush()
        sys.stdout.write("\n")
        sys.stdout.flush()
        return "".join(chars).strip()

    import termios
    import tty

    sys.stdout.write(prompt)
    sys.stdout.flush()
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            ch = sys.stdin.read(1)
            if ch in ("", "\r", "\n"):
                break
            if ch == "\x03":  # Ctrl-C
                raise KeyboardInterrupt
            if ch == "\x04":  # Ctrl-D
                if not chars:
                    raise EOFError
                break
            if ch in ("\x7f", "\x08"):  # backspace / delete
                if chars:
                    chars.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
                continue
            if ch == "\x15":  # Ctrl-U: clear the whole line
                while chars:
                    chars.pop()
                    sys.stdout.write("\b \b")
                sys.stdout.flush()
                continue
            if ch == "\x1b":  # swallow a full escape sequence (arrows, bracketed paste)
                if sys.stdin.read(1) == "[":
                    while True:
                        following = sys.stdin.read(1)
                        if not following or "@" <= following <= "~":
                            break
                continue
            if ch.isprintable():
                chars.append(ch)
                sys.stdout.write("•")
                sys.stdout.flush()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write("\r\n")
        sys.stdout.flush()
    return "".join(chars).strip()


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
    _draw_setup_header(step)
    print()
    _flush_notes()
    _print_select_text(title, style=_bold)
    if message:
        _print_select_text(message, style=_dim)
    if warning:
        _print_select_notice("Warning", warning, color=_yellow)
    if error:
        _print_select_notice("Needs attention", error, color=_red)
    print()
    spaced = any(description for _value, _label, description in options)
    for index, (_value, label, description) in enumerate(options):
        if spaced and index:
            print()
        _print_select_option(index == selected, label, description)
    print()
    hint = footer or f"↑/↓ move · enter confirm · 1–{min(len(options), 9)} jump"
    _print_select_text(hint, style=_dim)


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
            try:
                choice = input("> ").strip()
            except EOFError:
                # Piped/closed stdin (e.g. `yumi --setup </dev/null`) → default.
                return options[min(max(default, 0), len(options) - 1)][0]
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
        try:
            key = _read_key()
        except EOFError:
            # stdin closed mid-prompt — exit cleanly instead of spinning.
            raise SystemExit("  Setup cancelled.")
        if key == "up":
            selected = (selected - 1) % len(options)
        elif key == "down":
            selected = (selected + 1) % len(options)
        elif key == "enter":
            return options[selected][0]
        elif key.isdigit() and len(options) <= 9:
            # Single-digit shortcuts can only address up to 9 options; for
            # longer menus they'd be misleading (no way to reach item 10+), so
            # fall through to arrow-key navigation instead.
            idx = int(key)
            if 1 <= idx <= len(options):
                return options[idx - 1][0]


def _print_multi_option(checked: bool, is_cursor: bool, label: str, description: str) -> None:
    glyph = "◉" if checked else "○"
    bar = f"{_cyan('▌')} " if is_cursor else "  "
    glyph_render = _cyan(glyph) if checked else _dim(glyph)
    label_render = _bold_cyan(label) if is_cursor else label
    print(f"{bar}{glyph_render} {label_render}")
    if description:
        for line in _wrapped_select_lines(description, prefix=_DESC_INDENT):
            print(f"{_DESC_INDENT}{_dim(line)}")


def _select_multi(
    *,
    title: str,
    options: list[tuple[str, str, str]],
    step: str | None = None,
    message: str | None = None,
    warning: str | None = None,
    error: str | None = None,
    footer: str | None = None,
    preselected: set[str] | None = None,
    all_value: str = "__all__",
    all_label: str = "All",
    all_description: str = "",
    empty_means_all: bool = True,
) -> list[str]:
    """Pick 0..N options with checkboxes (space toggles, enter confirms).

    Returns the chosen real values in *options* order. When ``empty_means_all``
    is true, confirming with nothing checked returns every value. Off a TTY it
    falls back to a single numbered prompt accepting indices or value names.
    """
    reals = [value for value, _label, _description in options]
    checked: set[str] = set(preselected or set())

    if not _interactive_terminal():
        if step:
            print(step)
        print(title)
        if message:
            print(message)
        for i, (_value, label, _description) in enumerate(options, 1):
            print(f"  {i}. {label}")
        example = ", ".join(reals[:2])
        print(f"  Enter = all · comma/space separated (e.g. {example})")
        try:
            raw = input("> ").strip()
        except EOFError:
            raw = ""
        if not raw:
            return list(reals) if empty_means_all else []
        picked: set[str] = set()
        lowered = {value.lower(): value for value in reals}
        for token in raw.replace(",", " ").split():
            token = token.strip().lower()
            if token.isdigit() and 1 <= int(token) <= len(reals):
                picked.add(reals[int(token) - 1])
            elif token in lowered:
                picked.add(lowered[token])
        result = [value for value in reals if value in picked]
        return result or (list(reals) if empty_means_all else [])

    rendered = [(all_value, all_label, all_description), *options]
    cursor = 0
    while True:
        _clear_screen()
        _draw_setup_header(step)
        print()
        _flush_notes()
        _print_select_text(title, style=_bold)
        if message:
            _print_select_text(message, style=_dim)
        if warning:
            _print_select_notice("Warning", warning, color=_yellow)
        if error:
            _print_select_notice("Needs attention", error, color=_red)
        print()
        all_on = (not checked) or (checked == set(reals))
        for index, (value, label, description) in enumerate(rendered):
            is_checked = all_on if value == all_value else value in checked
            _print_multi_option(is_checked, index == cursor, label, description)
        print()
        _print_select_text(footer or "↑/↓ move · space toggle · a all/none · enter confirm", style=_dim)
        selected = [value for value in reals if value in checked]
        if not selected or len(selected) == len(reals):
            summary = f"Selected: {all_label.lower()}"
        else:
            summary = f"Selected: {', '.join(selected)}  ({len(selected)})"
        _print_select_text(summary, style=_dim)

        try:
            key = _read_key()
        except EOFError:
            raise SystemExit("  Setup cancelled.")
        if key == "up":
            cursor = (cursor - 1) % len(rendered)
        elif key == "down":
            cursor = (cursor + 1) % len(rendered)
        elif key == "enter":
            if not checked and empty_means_all:
                return list(reals)
            return [value for value in reals if value in checked]
        elif key == " ":
            value = rendered[cursor][0]
            if value == all_value:
                checked = set() if (not checked or checked == set(reals)) else set(reals)
            elif value in checked:
                checked.discard(value)
            else:
                checked.add(value)
        elif key in ("a", "A"):
            checked = set() if (checked == set(reals) or not checked) else set(reals)


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


# Credential fields written to disk by sub-steps (key prompts) rather than by the
# wizard's main config object. The driver merges these back before each save so it
# never overwrites a freshly-saved key with its stale in-memory copy.
_CREDENTIAL_FIELDS = (
    "openai_api_key",
    "gemini_api_key",
    "claude_api_key",
    "deepseek_api_key",
    "grok_api_key",
    "tts_api_key",
)

# Messaging bridge credentials are saved to disk by the Step 5 messaging callback
# (save_telegram_bot_token / save_discord_* / save_line_*), which mutate a freshly
# loaded config — never the wizard's long-lived ``config``. The per-step save must
# merge them back too, or it would wipe a token the user just entered.
_MESSAGING_FIELDS = (
    "telegram_bot_token",
    "telegram_allowed_user_ids",
    "discord_bot_token",
    "discord_allowed_user_ids",
    "line_channel_secret",
    "line_channel_access_token",
    "line_allowed_user_ids",
)


def _persist_tts_api_key(key: str) -> None:
    """Persist the shared DashScope (tts) key to disk immediately."""
    saved = load_saved_model_config()
    saved.tts_api_key = key
    save_model_config(saved)


def _merge_persisted_credentials(config: ModelConfig) -> None:
    """Re-apply API keys and bridge tokens that sub-steps saved to disk onto *config*.

    Key/token prompts persist via a freshly-loaded config (``_persist_tts_api_key``,
    the messaging ``save_*`` helpers, etc.), so the wizard's long-lived ``config``
    object is stale w.r.t. them. Without this merge, the driver's per-step
    ``save_model_config(config)`` clobbers the just-saved value with the empty
    in-memory one — which is why a key or bridge token entered during setup could
    vanish.
    """
    saved = load_saved_model_config()
    for field in (*_CREDENTIAL_FIELDS, *_MESSAGING_FIELDS):
        value = getattr(saved, field, None)
        if value:
            setattr(config, field, value)


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
            step="Step 1/5: AI model · Ollama",
            title=f"Choose a {label} model",
            options=options,
        )

        if action == "installed":
            model = _choose_installed_model(installed, label, step="Step 1/5: AI model · Ollama")
            if model:
                return model
            continue

        if action == "default" and rec:
            model = None
            with _normal_screen():
                print(f"\n  Downloading {rec} via Ollama...\n")
                try:
                    model = ensure_model_ready("ollama", rec)
                except Exception as exc:
                    _note(f"Failed to download {rec}: {exc}", ok=False)
            if model:
                return model
            continue

        if action == "manual":
            name = _framed_prompt(
                f"{label.capitalize()} model name",
                step="Step 1/5: AI model · Ollama · Model",
                hint="downloads it if missing · enter to go back",
            )
            if name:
                model = None
                with _normal_screen():
                    print(f"\n  Downloading {name} via Ollama...\n")
                    try:
                        model = ensure_model_ready("ollama", name)
                    except Exception as exc:
                        _note(f"Failed to prepare {name}: {exc}", ok=False)
                if model:
                    return model

        if action == "back":
            return None


def _prompt_model_name(provider_name: str, label: str) -> str | None:
    """Ask the user to choose or enter a model name for the given provider."""
    if provider_name == "ollama":
        return _prompt_ollama_model(label)

    model = _framed_prompt(
        f"{label.capitalize()} model name",
        step=f"Step 1/5: AI model · {_provider_label(provider_name)} · Model",
        hint="enter to go back",
    )
    return model or None


_WHISPER_MODELS = ("tiny", "base", "small", "medium", "large", "turbo")
_DEFAULT_WHISPER_MODEL_DIR = CONFIG_DIR / "models" / "whisper"
_STT_OPENAI_MODELS = ("gpt-4o-mini-transcribe", "gpt-4o-transcribe", "whisper-1")
_STT_GEMINI_MODELS = ("gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite")
_STT_DASHSCOPE_MODELS = ("qwen3-asr-flash",)
# (value, label, models) for each cloud transcription provider.
_STT_CLOUD_PROVIDERS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("openai", "OpenAI", _STT_OPENAI_MODELS),
    ("gemini", "Gemini", _STT_GEMINI_MODELS),
    ("dashscope", "DashScope (Qwen)", _STT_DASHSCOPE_MODELS),
)


def _ensure_dashscope_key(config: ModelConfig, step: str) -> bool:
    """Reuse-or-prompt the shared DashScope key (config.tts_api_key). False = back."""
    existing = config.tts_api_key or os.getenv("DASHSCOPE_API_KEY")
    title = "Connect your DashScope account"
    if existing:
        use_existing = _framed_prompt(
            "Use the saved DashScope key?  (Y/n)",
            step=step,
            title=title,
            context=f"A DashScope key is already saved ({_mask_secret(existing)}).",
            hint="enter to keep it · type n then enter to replace",
        ).lower()
        if use_existing not in ("n", "no"):
            os.environ["DASHSCOPE_API_KEY"] = existing
            config.tts_api_key = existing
            _persist_tts_api_key(existing)
            return True
        key = _framed_prompt(
            "New DashScope API key",
            step=step,
            title=title,
            hint="paste your key · shown as • · enter to go back",
            secret=True,
        )
    else:
        key = _framed_prompt(
            "DashScope API key",
            step=step,
            title=title,
            context="From Alibaba Cloud DashScope. Saved to ~/.yumi/config.json on this machine only.",
            hint="paste your key · shown as • · enter to go back",
            secret=True,
        )
    if not key:
        return False
    config.tts_api_key = key
    os.environ["DASHSCOPE_API_KEY"] = key
    _persist_tts_api_key(key)
    _note(f"DashScope key saved ({_mask_secret(key)}).")
    return True


def _ensure_cloud_voice_key(config: ModelConfig, provider: str, label: str, step: str) -> bool:
    """Ensure the API key for a cloud STT/TTS provider (DashScope is shared/special)."""
    if provider == "dashscope":
        return _ensure_dashscope_key(config, step)
    return _ensure_api_key(provider, label, step)


def _setup_cloud_stt(config: ModelConfig) -> bool:
    """Pick a cloud transcription provider + model. False = go back."""
    from yumi.core.features.config.feature_install import ensure_feature_installed

    while True:
        options = [(value, label, "") for value, label, _models in _STT_CLOUD_PROVIDERS]
        options.append(("back", "← Back", ""))
        provider = _select_option(
            step="Step 3/5: Voice input (speech-to-text) · Provider",
            title="Which cloud transcription provider?",
            message="All reuse a key you may already have; nothing is downloaded.",
            options=options,
        )
        if provider == "back":
            return False
        label, models = next((lab, mods) for val, lab, mods in _STT_CLOUD_PROVIDERS if val == provider)
        if not _ensure_cloud_voice_key(config, provider, label, f"Step 3/5: Voice input · {label} · API key"):
            continue
        model_options = [(name, name, "") for name in models]
        model_options.append(("back", "← Back", ""))
        model = _select_option(
            step=f"Step 3/5: Voice input (speech-to-text) · {label} · Model",
            title=f"Choose a {label} transcription model",
            options=model_options,
        )
        if model == "back":
            continue
        config.stt_provider = provider
        config.stt_backend = ""
        config.stt_model = model
        config.stt_model_dir = None
        config.stt_language = "auto"
        if provider == "dashscope":
            with _normal_screen():
                print("\n  Installing DashScope support...\n")
                if not ensure_feature_installed("tts", assume_yes=True):
                    _note("DashScope package isn't installed yet; transcription starts once it is.", ok=False)
                    return True
        _note(f"Voice input ready: {provider} · {model}")
        return True


def _setup_local_stt(config: ModelConfig) -> bool:
    """Pick + cache a local Whisper model. False = go back."""
    from yumi.core.features.config.feature_install import ensure_feature_installed

    options = [(name, name, "") for name in _WHISPER_MODELS]
    options.append(("back", "← Back", ""))
    model = _select_option(
        step="Step 3/5: Voice input (speech-to-text) · Whisper model",
        title="Choose a Whisper multilingual model",
        message="Larger = more accurate, but slower and bigger to download.",
        options=options,
    )
    if model == "back":
        return False
    config.stt_provider = "whisper"
    config.stt_backend = "faster-whisper"
    config.stt_model = model
    config.stt_model_dir = str(_DEFAULT_WHISPER_MODEL_DIR)
    config.stt_language = "auto"

    # Install + weight download go on the normal screen (own progress output).
    with _normal_screen():
        print(f"\n  Preparing Whisper '{model}' — installing support and caching weights.\n")
        if not ensure_feature_installed("stt", assume_yes=True):
            _note(
                "Voice input saved, but the package isn't installed yet — re-run `yumi --setup` to cache it.",
                ok=False,
            )
            return True
        try:
            from yumi.core.features.stt.whisper_provider import ensure_whisper_weights_cached

            ensure_whisper_weights_cached(model=model, model_dir=config.stt_model_dir)
        except Exception as exc:
            _note(f"Could not prepare Whisper weights: {exc} — it retries on first use.", ok=False)
            return True
    _note(f"Voice input ready: whisper / {model}")
    return True


def _prompt_stt_config(config: ModelConfig) -> str:
    """Ask for optional STT settings and mutate *config*. Returns 'back'/'next'."""
    while True:
        # "keep" only when voice input is already configured — nothing to keep on
        # a first run, where the option would just be confusing.
        options: list[tuple[str, str, str]] = []
        if config.stt_provider not in ("", "disabled"):
            options.append(
                ("keep", "Keep current voice input", f"{config.stt_provider} / {config.stt_model or 'unset'}")
            )
        options += [
            ("cloud", "Cloud transcription", "OpenAI · Gemini · DashScope; nothing to download"),
            ("local", "Local Whisper", "fully offline; downloads a multilingual model"),
            ("disable", "Skip / disable voice input", ""),
            ("back", "← Back to previous step", ""),
        ]
        choice = _select_option(
            step="Step 3/5: Voice input (speech-to-text)",
            title="Configure speech-to-text (STT) for voice messages?",
            options=options,
        )
        if choice == "back":
            return "back"
        if choice == "keep":
            _note(f"Kept voice input: {config.stt_provider} / {config.stt_model or 'unset'}")
            return "next"
        if choice == "disable":
            config.stt_provider = "disabled"
            config.stt_backend = "faster-whisper"
            config.stt_model = None
            config.stt_language = "auto"
            _note("Voice input disabled. Re-run `yumi --setup` to enable it.")
            return "next"
        if choice == "cloud":
            if _setup_cloud_stt(config):
                return "next"
            continue
        if choice == "local":
            if _setup_local_stt(config):
                return "next"
            continue


# ── text-to-speech (spoken replies) ─────────────────────────────────────────

# Curated voice shortlists (both backends accept more — type a name to override).
_TTS_DASHSCOPE_VOICES = ("Cherry", "Serena", "Ethan", "Chelsie", "Dylan", "Eric", "Ryan", "Jada", "Sunny")
_TTS_OPENAI_VOICES = ("alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer")
# (value, label, voices, default_voice) for each cloud voice provider.
_TTS_CLOUD_PROVIDERS: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    ("dashscope", "Qwen3-TTS (DashScope)", _TTS_DASHSCOPE_VOICES, "Cherry"),
    ("openai", "OpenAI", _TTS_OPENAI_VOICES, "alloy"),
)


def _prompt_tts_voice(label: str, voices: tuple[str, ...], default: str) -> str:
    options = [(name, name, "default" if name == default else "") for name in voices]
    options.append(("custom", "Enter a custom voice name", ""))
    selected = _select_option(
        step="Step 4/5: Spoken replies (text-to-speech) · Voice",
        title=f"Choose a {label} voice",
        options=options,
        default=voices.index(default) if default in voices else 0,
    )
    if selected == "custom":
        custom = _framed_prompt(
            "Voice name",
            step="Step 4/5: Spoken replies · Voice",
            hint="enter for the default",
        )
        return custom or default
    if not selected:
        return default
    return selected


def _setup_cloud_tts(config: ModelConfig) -> bool:
    """Pick a cloud voice provider + voice. False = go back."""
    from yumi.core.features.config.feature_install import ensure_feature_installed

    while True:
        options = [(value, label, "") for value, label, _voices, _default in _TTS_CLOUD_PROVIDERS]
        options.append(("back", "← Back", ""))
        provider = _select_option(
            step="Step 4/5: Spoken replies (text-to-speech) · Provider",
            title="Which cloud voice provider?",
            message="Both reuse a key you may already have.",
            options=options,
        )
        if provider == "back":
            return False
        label, voices, default = next((lab, vo, df) for val, lab, vo, df in _TTS_CLOUD_PROVIDERS if val == provider)
        if not _ensure_cloud_voice_key(config, provider, label, f"Step 4/5: Spoken replies · {label} · API key"):
            continue
        voice = _prompt_tts_voice(label, voices, default)
        config.tts_provider = provider
        config.tts_model = None
        config.tts_voice = voice
        if provider == "dashscope":
            with _normal_screen():
                print("\n  Installing DashScope support...\n")
                if not ensure_feature_installed("tts", assume_yes=True):
                    _note("DashScope package isn't installed yet; spoken replies start once it is.", ok=False)
                    return True
        _note(f"Spoken replies: {provider} · {voice}")
        return True


def _setup_local_tts(config: ModelConfig) -> bool:
    """Pick a local voice backend. False = go back."""
    from yumi.core.features.config.feature_install import ensure_feature_installed

    choice = _select_option(
        step="Step 4/5: Spoken replies (text-to-speech) · Local",
        title="Local spoken-reply backend",
        options=[
            ("system", "System voice", "macOS say / Linux espeak; offline, no key, instant"),
            ("qwen", "Local Qwen3-TTS", "highest local quality; heavy, needs a CUDA GPU"),
            ("back", "← Back", ""),
        ],
    )
    if choice == "back":
        return False
    if choice == "system":
        config.tts_provider = "system"
        config.tts_voice = None
        _note("Spoken replies: system voice.")
        return True
    config.tts_provider = "qwen"
    config.tts_model = None
    config.tts_voice = None
    with _normal_screen():
        print("\n  Installing local Qwen3-TTS (heavy; needs a GPU)...\n")
        if not ensure_feature_installed("tts-local", assume_yes=True):
            _note("Local Qwen3-TTS isn't installed yet; spoken replies start once it is.", ok=False)
            return True
    _note("Spoken replies: local Qwen3-TTS.")
    return True


def _prompt_tts_config(config: ModelConfig) -> str:
    """Ask for optional spoken-reply (TTS) settings and mutate *config*. Returns 'back'/'next'."""
    while True:
        # "keep" only when spoken replies are already configured.
        options: list[tuple[str, str, str]] = []
        if config.tts_provider not in ("", "disabled"):
            options.append(("keep", "Keep current spoken replies", config.tts_provider))
        options += [
            ("cloud", "Cloud voice", "DashScope · OpenAI; best quality, needs a key"),
            ("local", "Local / system voice", "offline, no key"),
            ("disable", "Skip / disable", ""),
            ("back", "← Back to previous step", ""),
        ]
        choice = _select_option(
            step="Step 4/5: Spoken replies (text-to-speech)",
            title="Enable spoken replies (text-to-speech)?",
            options=options,
        )
        if choice == "back":
            return "back"
        if choice == "keep":
            _note(f"Kept spoken replies: {config.tts_provider}")
            return "next"
        if choice == "disable":
            config.tts_provider = "disabled"
            _note("Spoken replies off. Re-run `yumi --setup` to enable them.")
            return "next"
        if choice == "cloud":
            if _setup_cloud_tts(config):
                return "next"
            continue
        if choice == "local":
            if _setup_local_tts(config):
                return "next"
            continue


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
        step="Step 1/5: AI model · Run mode",
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
            ("exit", "Exit setup", ""),
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
        step="Step 1/5: AI model · Provider",
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
            step=f"Step 1/5: AI model · {_provider_label(provider)} · Model",
            title=f"Choose a {label} model for {_provider_label(provider)}",
            options=options,
        )
        if selected in models:
            return selected
        if selected == "custom":
            name = _framed_prompt(
                f"{label.capitalize()} model name",
                step=f"Step 1/5: AI model · {_provider_label(provider)} · Model",
                title=f"Custom {label} model for {_provider_label(provider)}",
                hint="enter to go back",
            )
            if name:
                return name
            continue
        if selected == "back":
            return None


def _ensure_chat_provider_api_key(provider: str) -> bool:
    target = _api_key_target(provider)
    if target is None:
        return True
    env_var, _field = target
    label = _provider_label(provider)
    step = f"Step 1/5: AI model · {label} · API key"
    title = f"Connect your {label} account"
    existing = _existing_api_key(provider)
    if existing:
        use_existing = _framed_prompt(
            "Use the saved key?  (Y/n)",
            step=step,
            title=title,
            context=f"A {label} key is already saved ({_mask_secret(existing)}).",
            hint="enter to keep it · type n then enter to replace",
        ).lower()
        if use_existing not in ("n", "no"):
            os.environ[env_var] = existing
            return True
        key = _framed_prompt(
            f"New {label} API key",
            step=step,
            title=title,
            hint="paste your key · shown as • · enter to go back",
            secret=True,
        )
    else:
        key = _framed_prompt(
            f"{label} API key",
            step=step,
            title=title,
            context=f"Yumi saves it to {CONFIG_PATH} on this machine only.",
            hint="paste your key · shown as • · enter to go back",
            secret=True,
        )
    if not key:
        print("  A working chat provider is required to continue.")
        return False
    _persist_cloud_api_key(provider, key, announce=False)
    _note(f"{label} API key saved ({_mask_secret(key)}).")
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

        # local (Ollama): surface connection errors inline with a Retry option,
        # instead of bouncing the user all the way back to the run-mode screen.
        while True:
            try:
                ensure_provider_available("ollama")
            except Exception as exc:
                choice = _select_option(
                    step="Step 1/5: AI model · Ollama",
                    title="Ollama isn't reachable yet",
                    error=(
                        "Install it from https://ollama.com and start it (run `ollama serve`), "
                        f"then retry.\nDetails: {exc}"
                    ),
                    options=[
                        ("retry", "Retry connection", ""),
                        ("runmode", "← Back to run mode", ""),
                    ],
                )
                if choice == "retry":
                    continue
                break
            chat_model = _prompt_model_name("ollama", "chat")
            if chat_model is None:
                break
            return "ollama", chat_model


def _cloud_embedding_options(chat_provider: str) -> list[tuple[str, str]]:
    options = list(_CLOUD_EMBEDDING_PROVIDERS)
    if chat_provider in {key for key, _label in options}:
        options.sort(key=lambda pair: pair[0] != chat_provider)
    return options


def _ensure_api_key(provider: str, label: str, step: str) -> bool:
    """Reuse-or-prompt a cloud provider's API key (masked). False = go back."""
    target = _api_key_target(provider)
    if target is None:
        return False
    env_var, _field = target
    title = f"Connect your {label} account"
    existing = _existing_api_key(provider)
    if existing:
        use_existing = _framed_prompt(
            "Use the saved key?  (Y/n)",
            step=step,
            title=title,
            context=f"A {label} key is already saved ({_mask_secret(existing)}).",
            hint="enter to keep it · type n then enter to replace",
        ).lower()
        if use_existing not in ("n", "no"):
            os.environ[env_var] = existing
            return True
        key = _framed_prompt(
            f"New {label} API key",
            step=step,
            title=title,
            hint="paste your key · shown as • · enter to go back",
            secret=True,
        )
    else:
        key = _framed_prompt(
            f"{label} API key",
            step=step,
            title=title,
            context=f"Yumi saves it to {CONFIG_PATH} on this machine only.",
            hint="paste your key · shown as • · enter to go back",
            secret=True,
        )
    if not key:
        return False
    _persist_cloud_api_key(provider, key, announce=False)
    _note(f"{label} API key saved ({_mask_secret(key)}).")
    return True


def _ensure_cloud_embedding_key(provider: str, label: str) -> bool:
    return _ensure_api_key(provider, label, f"Step 2/5: Memory · {label} · API key")


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
        _note(f"Cloud embeddings configured with {label}.")
        return True


def _prepare_fastembed_model(model: str, size_label: str) -> bool:
    from yumi.core.features.config.feature_install import ensure_feature_installed

    # Drop to the normal screen: the pip install + download progress bar belong
    # there, not on the wizard's alternate screen where a late flush would stick.
    with _normal_screen():
        print()
        print(f"  Installing local embedding support and downloading {model} ({size_label}).")
        print("  This can take a few minutes the first time.\n")
        if not ensure_feature_installed("embed", assume_yes=True):
            _note("Local embeddings aren't ready — choose another backend or retry later.", ok=False)
            return False
        try:
            _get_provider("fastembed").pull_model(model)
        except Exception as exc:
            _note(f"Could not prepare local embedding model: {exc}", ok=False)
            return False
    _note("Local embedding model is ready.")
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
            model_name = _framed_prompt(
                "Ollama embedding model name",
                step="Step 2/5: Memory · Ollama · Model",
                hint="downloads it if missing · enter to go back",
            )
            if not model_name:
                continue
            model = None
            with _normal_screen():
                print(f"\n  Downloading {model_name} via Ollama...\n")
                try:
                    model = ensure_model_ready("ollama", model_name)
                except Exception as exc:
                    notice = f"Failed to prepare Ollama embedding model {model_name!r}.\nDetails: {exc}"
            if not model:
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
            ("back", "← Back to previous step", ""),
        ],
    )


def _configure_embeddings(config: ModelConfig, chat_provider: str) -> str:
    """Embedding backend selection with backtracking submenus. Returns 'back'/'next'."""
    while True:
        choice = _select_option(
            step="Step 2/5: Memory (text embeddings) · Backend",
            title="Choose an embedding backend",
            message="Embeddings improve memory search and Edge tool routing.",
            warning=_EMBEDDING_STABILITY_WARNING,
            options=[
                ("cloud", "Cloud embeddings", ""),
                ("local", "Local embeddings", "Yumi installs and downloads everything from the CLI"),
                ("ollama", "Ollama embeddings", "requires Ollama already installed and running"),
                ("skip", "Skip embeddings for now", "memory and tool-routing quality will be reduced"),
                ("back", "← Back to previous step", ""),
            ],
        )
        if choice == "cloud":
            if _setup_cloud_embeddings(config, chat_provider):
                return "next"
            continue
        if choice == "local":
            if _setup_fastembed_embeddings(config):
                return "next"
            continue
        if choice == "ollama":
            if _setup_ollama_embeddings(config):
                return "next"
            continue
        if choice == "skip":
            config.embedding_provider = "disabled"
            config.embedding_model = None
            _note("Memory embeddings skipped. Re-run `yumi --setup` to enable them.")
            return "next"
        if choice == "back":
            return "back"


def _setup_embeddings(config: ModelConfig, chat_provider: str) -> str:
    """Returns 'back' (to previous step) or 'next'."""
    action = _choose_embedding_action(config)
    if action == "back":
        return "back"
    if action == "keep":
        _note(f"Kept memory: {config.embedding_provider} / {config.embedding_model}")
        return "next"
    return _configure_embeddings(config, chat_provider)


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


def _bridges_label() -> str:
    """Names of any messaging bridges that already have credentials, else 'none'."""
    try:
        from yumi.core.features.config import (
            get_discord_bot_token,
            get_line_channel_access_token,
            get_line_channel_secret,
            get_telegram_bot_token,
        )
    except Exception:
        return "none"
    active = []
    if get_telegram_bot_token():
        active.append("Telegram")
    if get_discord_bot_token():
        active.append("Discord")
    if get_line_channel_secret() and get_line_channel_access_token():
        active.append("LINE")
    return " · ".join(active) if active else "none"


def _summary_rows(config: ModelConfig) -> list[tuple[str, str]]:
    memory = f"{config.embedding_provider} · {config.embedding_model}" if config.embedding_model else "off"
    if config.stt_model and config.stt_provider not in ("", "disabled"):
        voice_in = f"{config.stt_provider} · {config.stt_model}"
    else:
        voice_in = "off"
    replies = config.tts_provider if config.tts_provider not in ("", "disabled") else "off"
    if config.tts_voice and replies != "off":
        replies = f"{replies} · {config.tts_voice}"
    return [
        ("Chat", f"{config.chat_provider} · {config.chat_model}"),
        ("Memory", memory),
        ("Voice in", voice_in),
        ("Replies", replies),
        ("Bridges", _bridges_label()),
    ]


def _render_setup_summary(config: ModelConfig) -> None:
    """The closing screen: a calm completion lockup, not a stack of prints."""
    rows = _summary_rows(config)
    if not _interactive_terminal():
        _flush_notes()
        print()
        print(f"Saved Yumi model config to {CONFIG_PATH}.")
        for key, value in rows:
            print(f"{key}: {value}")
        return

    # No _clear_screen(): this renders after the alternate screen is torn down,
    # so it stays in the normal scrollback as a lasting record of the config.
    print()
    width = _page_width()
    rail = " ".join(_cyan("●") for _ in range(5))
    print(f"{_SELECT_TEXT_PAD}{rail}   {_dim('Setup complete')}")
    print(f"{_SELECT_TEXT_PAD}{_dim('─' * (width - 2))}")
    print()
    _flush_notes()
    print(f"{_SELECT_TEXT_PAD}{_green('✓')} {_bold('Yumi is ready.')}")
    print(f"{_SELECT_TEXT_PAD}{_dim('Saved to ' + str(CONFIG_PATH))}")
    print()
    key_width = max(len(key) for key, _ in rows)
    for key, value in rows:
        rendered = _dim(value) if value in ("off", "none") else value
        print(f"{_SELECT_TEXT_PAD}{_dim(key.ljust(key_width))}   {rendered}")
    print()
    print(
        f"{_SELECT_TEXT_PAD}{_dim('Start anytime with')} {_bold('yumi')}"
        f"   {_dim('·  change settings with')} {_bold('yumi --setup')}"
    )


def _step_chat(config: ModelConfig, current: ModelConfig) -> str:
    chat_action = _choose_chat_action(current)
    if chat_action == "exit":
        return "exit"
    if chat_action == "keep":
        _note(f"Kept chat model: {config.chat_provider} / {config.chat_model}")
        return "next"
    chat_provider, chat_model = _configure_chat_model()  # raises SystemExit on run-mode exit
    config.chat_provider = chat_provider
    config.chat_model = chat_model
    return "next"


def _step_embeddings(config: ModelConfig) -> str:
    return _setup_embeddings(config, config.chat_provider)


def _step_messaging(messaging) -> str:
    result = messaging()
    return result if result in ("back", "next") else "next"


def run_model_setup(force: bool = False, *, messaging=None) -> ModelConfig:
    current = load_saved_model_config()
    if current.chat_model and not force:
        return load_model_config()

    _PENDING_NOTES.clear()
    config = load_saved_model_config()
    config.system_prompt = current.system_prompt

    if not _interactive_terminal():
        print("Welcome to Yumi.")
        print("Let's set you up — first choose a working chat model; the remaining steps are optional.\n")

    # Steps form a navigable sequence: each returns "next" / "back" / "exit", so a
    # mistake in an early step no longer forces a full re-run.
    steps: list[tuple[str, Callable[[], str]]] = [
        ("Step 1/5: AI model", lambda: _step_chat(config, current)),
        ("Step 2/5: Memory (text embeddings)", lambda: _step_embeddings(config)),
        ("Step 3/5: Voice input (speech-to-text)", lambda: _prompt_stt_config(config)),
        ("Step 4/5: Spoken replies (text-to-speech)", lambda: _prompt_tts_config(config)),
    ]
    if messaging is not None:
        steps.append(("Step 5/5: Messaging bridges", lambda: _step_messaging(messaging)))

    with _alt_screen():
        idx = 0
        while idx < len(steps):
            label, run_step = steps[idx]
            if not _interactive_terminal():
                print(f"\n── {label} ──")
            status = run_step()
            if status == "back":
                idx = max(0, idx - 1)
                continue
            if status == "exit":
                raise SystemExit("  Setup cancelled.")
            _merge_persisted_credentials(config)
            save_model_config(config)
            idx += 1

    _render_setup_summary(config)
    return config
