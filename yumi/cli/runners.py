"""Implementation of the Yumi CLI sub-commands.

Each ``run_*`` helper performs one sub-command's work. They are wired to
argparse-driven :class:`~yumi.cli.registry.Command` classes in
:mod:`yumi.cli.commands`; :func:`yumi.cli.main` is the entry point. Kept in a
dedicated module so ``yumi/cli/__init__.py`` stays a thin entry point.
"""

import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from yumi.core.features.config import (
    CONFIG_PATH,
    cleanup_memory_data,
    cleanup_user_data,
    embeddings_enabled,
    ensure_chat_model_configured,
    ensure_full_model_config_file,
    ensure_provider_available,
    get_discord_bot_token,
    get_lan_secret,
    get_line_channel_access_token,
    get_line_channel_secret,
    get_saved_connection_code,
    get_telegram_bot_token,
    load_model_config,
    load_saved_model_config,
    run_model_setup,  # noqa: F401 — re-exported for `yumi.cli.commands.SetupCommand`
    save_connection_code,
    save_discord_bot_token,
    save_line_channel_access_token,
    save_line_channel_secret,
    save_model_config,
    save_telegram_bot_token,
)
from yumi.core.platform.security.auth import _LEGACY_LAN_PREFIXES, LAN_TOKEN_PREFIX
from yumi.core.platform.security.connection import (
    build_lan_server_url,
    discover_lan_ips,
    issue_lan_code,
    parse_lan_code,
)
from yumi.edge.client import init_workspace

SERVER_URL = os.getenv("YUMI_SERVER_URL", "http://127.0.0.1:8000")
UI_FRONTEND_PORT = 3000
UI_BACKEND_PORT = 8001


def server_health_url(base_url: str | None = None) -> str:
    target_base = (base_url or SERVER_URL).rstrip("/")
    return f"{target_base}/health"


def is_server_running(url: str | None = None):
    try:
        with urllib.request.urlopen(url or server_health_url(), timeout=3) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _wait_for_server_health(base_url: str, timeout: float = 90) -> bool:
    """Poll /health until OK or timeout."""
    deadline = time.time() + timeout
    health_url = server_health_url(base_url)
    while time.time() < deadline:
        if is_server_running(health_url):
            return True
        time.sleep(0.5)
    return False


def _prompt_telegram_bot_token_if_missing() -> bool:
    """If no token in env/config, prompt on TTY and save to ~/.yumi/config.json."""
    if get_telegram_bot_token():
        return True
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print(f"\n  Telegram bot token required. Set TELEGRAM_BOT_TOKEN or add telegram_bot_token to {CONFIG_PATH}\n")
        return False
    print()
    print("  No Telegram bot token found.")
    print("  In Telegram, open @BotFather, send /newbot, then copy the token.")
    print()
    while True:
        try:
            line = input("  Paste bot token (Enter to exit): ").strip()
        except EOFError:
            print("  Exiting.\n")
            return False
        if not line:
            print("  Exiting.\n")
            return False
        if ":" not in line:
            print("  A BotFather token usually looks like 123456789:ABC-DEF... Try again.\n")
            continue
        try:
            save_telegram_bot_token(line)
        except ValueError as exc:
            print(f"  {exc}\n")
            continue
        print(f"  Token saved to {CONFIG_PATH}\n")
        return True


def _prompt_discord_bot_token_if_missing() -> bool:
    """If no token in env/config, prompt on TTY and save to ~/.yumi/config.json."""
    if get_discord_bot_token():
        return True
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print(f"\n  Discord bot token required. Set DISCORD_BOT_TOKEN or add discord_bot_token to {CONFIG_PATH}\n")
        return False
    print()
    print("  No Discord bot token found.")
    print("  In the Discord Developer Portal, create an application + bot, enable the")
    print("  MESSAGE CONTENT intent, then copy the bot token.")
    print()
    while True:
        try:
            line = input("  Paste bot token (Enter to exit): ").strip()
        except EOFError:
            print("  Exiting.\n")
            return False
        if not line:
            print("  Exiting.\n")
            return False
        try:
            save_discord_bot_token(line)
        except ValueError as exc:
            print(f"  {exc}\n")
            continue
        print(f"  Token saved to {CONFIG_PATH}\n")
        return True


def _prompt_line_credentials_if_missing() -> bool:
    """If LINE secret/token missing, prompt on TTY and save to ~/.yumi/config.json."""
    if get_line_channel_secret() and get_line_channel_access_token():
        return True
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print(
            "\n  LINE webhook requires LINE_CHANNEL_SECRET and LINE_CHANNEL_ACCESS_TOKEN "
            f"(or line_* fields in {CONFIG_PATH}).\n"
        )
        return False
    print()
    print("  No LINE Messaging API credentials found.")
    print("  From LINE Developers Console: Channel secret + long-lived channel access token.")
    print()
    try:
        secret = input("  Channel secret (Enter to abort): ").strip()
    except EOFError:
        print("  Exiting.\n")
        return False
    if not secret:
        print("  Exiting.\n")
        return False
    try:
        access = input("  Channel access token: ").strip()
    except EOFError:
        print("  Exiting.\n")
        return False
    if not access:
        print("  Exiting.\n")
        return False
    try:
        save_line_channel_secret(secret)
        save_line_channel_access_token(access)
    except ValueError as exc:
        print(f"  {exc}\n")
        return False
    print(f"  Saved to {CONFIG_PATH}\n")
    return True


def setup_messaging_tokens() -> None:
    """Optional Step 5 of ``yumi --setup`` for messaging bridge credentials."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return

    from yumi.core.features.config.setup_wizard import _select_option

    while True:
        options = [
            (
                "telegram",
                "Telegram",
                "configured" if get_telegram_bot_token() else "set bot token",
            ),
            (
                "discord",
                "Discord",
                "configured" if get_discord_bot_token() else "set bot token",
            ),
            (
                "line",
                "LINE",
                "configured"
                if get_line_channel_secret() and get_line_channel_access_token()
                else "set channel secret and access token",
            ),
            ("skip", "Skip messaging setup", ""),
        ]
        choice = _select_option(
            step="Step 5/5: Messaging bridges",
            title="Configure messaging bridges?",
            message=(
                "Optional. You can chat with Yumi from Telegram, Discord, or LINE. "
                "Missing credentials can also be filled later when you start a bridge."
            ),
            options=options,
        )
        if choice == "telegram":
            _prompt_telegram_bot_token_if_missing()
            continue
        if choice == "discord":
            _prompt_discord_bot_token_if_missing()
            continue
        if choice == "line":
            _prompt_line_credentials_if_missing()
            continue
        return


# ── connection code prompt ──


def _is_lan_code(code: str) -> bool:
    if code.startswith(LAN_TOKEN_PREFIX):
        return True
    return any(code.startswith(p) for p in _LEGACY_LAN_PREFIXES)


def _validate_lan_code(code: str) -> bool:
    """Check if a LAN code points to a reachable server."""
    try:
        server_url = parse_lan_code(code)
        return is_server_running(server_health_url(server_url))
    except (ValueError, Exception):
        return False


def _prompt_connection_code(prompt_text: str, *, allow_empty: bool = True) -> str | None:
    """Try saved connection code first; prompt if unavailable or invalid."""
    saved = get_saved_connection_code()

    if saved:
        if _is_lan_code(saved):
            if _validate_lan_code(saved):
                try:
                    server_url = parse_lan_code(saved)
                except ValueError:
                    server_url = saved
                masked = saved[:8] + "..." + saved[-4:] if len(saved) > 12 else saved
                print(f"  Using saved connection code ({masked} -> {server_url})")
                return saved
            print("  Saved connection code is no longer reachable.")
        else:
            print("  Using saved connection code.")
            return saved

    code = input(f"  {prompt_text}").strip()
    if not code:
        return None

    save_connection_code(code)
    return code


# ── display helpers ──


def _print_banner(title: str, rows: list[tuple[str, str]], notes: list[str] | None = None):
    min_width = 48
    title_len = len(f"  ✨ {title}")
    max_label = max((len(label) for label, _ in rows), default=0) if rows else 0
    content_widths = [len(f"  {label:<{max_label}}  {value}") for label, value in rows] if rows else []
    note_widths = [len(f"  {n}") for n in (notes or [])]
    width = max(min_width, title_len + 2, *(content_widths + note_widths)) + 2

    border = "─" * width
    print()
    print(f"  ┌{border}┐")
    print(f"  │  ✨ {title:<{width - 5}}│")
    print(f"  ├{border}┤")
    if rows:
        for label, value in rows:
            line = f"  {label:<{max_label}}  {value}"
            print(f"  │{line:<{width}}│")
    if notes:
        print(f"  ├{border}┤")
        for note in notes:
            print(f"  │  {note:<{width - 2}}│")
    print(f"  └{border}┘")
    print()


def _get_lan_ip() -> str | None:
    lan_ips = discover_lan_ips()
    return lan_ips[0] if lan_ips else None


# ── server ──


def _subprocess_env_ensure_platform_tokens() -> dict:
    """Inject Telegram / LINE secrets into the API child env when missing (timer push, etc.)."""
    env = os.environ.copy()
    token = get_telegram_bot_token()
    if token and not (env.get("TELEGRAM_BOT_TOKEN") or "").strip():
        env["TELEGRAM_BOT_TOKEN"] = token
    dc = get_discord_bot_token()
    if dc and not (env.get("DISCORD_BOT_TOKEN") or "").strip():
        env["DISCORD_BOT_TOKEN"] = dc
    ls = get_line_channel_secret()
    if ls and not (env.get("LINE_CHANNEL_SECRET") or "").strip():
        env["LINE_CHANNEL_SECRET"] = ls
    lt = get_line_channel_access_token()
    if lt and not (env.get("LINE_CHANNEL_ACCESS_TOKEN") or "").strip():
        env["LINE_CHANNEL_ACCESS_TOKEN"] = lt
    return env


def _server_banner_rows(config) -> list[tuple[str, str]]:
    from yumi.core.platform.tools.tool import TOOL_REGISTRY
    from yumi.tools.bootstrap import init_yumi

    init_yumi()
    tool_count = len(TOOL_REGISTRY)

    lan_ip = _get_lan_ip()
    rows: list[tuple[str, str]] = [
        ("Local:", "http://127.0.0.1:8000"),
    ]
    if lan_ip:
        rows.append(("Network:", f"http://{lan_ip}:8000"))
    rows.append(("", ""))
    rows.append(("Chat:", f"{config.chat_provider} / {config.chat_model}"))
    rows.append(("Embed:", f"{config.embedding_provider} / {config.embedding_model}"))
    rows.append(("Tools:", f"{tool_count} registered"))
    return rows


def _print_lan_codes() -> None:
    lan_ip = _get_lan_ip()
    if not lan_ip:
        return
    lan_secret = get_lan_secret()
    base_url = build_lan_server_url(lan_ip)
    permanent_code = issue_lan_code(base_url, expires_at=0, secret=lan_secret)
    temp_expires = int(time.time()) + 86400
    temp_code = issue_lan_code(base_url, expires_at=temp_expires, secret=lan_secret)
    print(f"  LAN Code:       {permanent_code}")
    print(f"  Temp Code (24h): {temp_code}")
    print()


def _preflight_models():
    """Make sure a chat model is configured and its provider is reachable.

    Order matters: configure first (env auto-detect or the interactive wizard),
    *then* check provider readiness — so a fresh user without Ollama isn't hard
    -crashed before they can pick a cloud API key. Exits with a friendly hint on
    failure instead of a traceback.
    """
    config = load_model_config()
    if not config.chat_model:
        config = ensure_chat_model_configured(interactive=True)

    try:
        ensure_provider_available(config.chat_provider)
    except Exception as exc:
        print()
        print(f"  Cannot start: chat provider '{config.chat_provider}' is not ready.")
        print(f"  {exc}")
        if config.chat_provider == "ollama":
            print("  Tip: install/start Ollama (https://ollama.com), or run `yumi --setup` to use a cloud API key.")
        else:
            print("  Tip: run `yumi --setup` to set the API key, or export it (e.g. OPENAI_API_KEY).")
        sys.exit(1)

    if embeddings_enabled(config) and config.embedding_provider != config.chat_provider:
        try:
            ensure_provider_available(config.embedding_provider)
        except Exception as exc:
            print(f"  Warning: embedding provider '{config.embedding_provider}' not available: {exc}")
            print("  Long-term memory search stays degraded until it's reachable.")
    return config


def run_server():
    config = _preflight_models()

    rows = _server_banner_rows(config)
    _print_banner("Yumi Server", rows, ["Mode: local / LAN (single user)"])
    _print_lan_codes()

    subprocess.run([sys.executable, "-m", "yumi.core.api"], env=_subprocess_env_ensure_platform_tokens())


def run_server_with_bridges(
    *,
    telegram: bool = False,
    discord: bool = False,
    line: bool = False,
    voice: bool = False,
) -> None:
    """Start the Yumi API (subprocess) plus any selected messaging bridges.

    Each messaging bridge (Telegram / Discord / LINE) runs in its OWN subprocess,
    so several can run at once — e.g. ``yumi --server --telegram --discord``.
    Voice attaches inside the API process via an env flag (not a separate bot).
    Ctrl+C stops the server and every bridge.
    """
    if telegram and not _prompt_telegram_bot_token_if_missing():
        sys.exit(1)
    if discord and not _prompt_discord_bot_token_if_missing():
        sys.exit(1)
    if line and not _prompt_line_credentials_if_missing():
        sys.exit(1)

    config = _preflight_models()

    server_env = _subprocess_env_ensure_platform_tokens()
    bind_host = (server_env.get("YUMI_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    bind_port = (server_env.get("YUMI_PORT") or "8000").strip() or "8000"
    if bind_host in ("0.0.0.0", "::"):
        notes = [f"Mode: LAN-exposed on {bind_host}:{bind_port} (single user, NO auth in L1 — trust your network)"]
    else:
        notes = [f"Mode: loopback only ({bind_host}:{bind_port}); use --host 0.0.0.0 to expose on your LAN"]
    if voice:
        owner = (config.voice_owner_id or os.getenv("USER") or os.getenv("USERNAME") or "default").strip() or "default"
        server_env["YUMI_VOICE_ENABLED"] = "1"
        server_env["YUMI_VOICE_OWNER_ID"] = owner
        notes.append(f"Voice: wake-word loop attached (owner={owner}, wake='{config.voice_wake_word}')")
        if not (config.voice_porcupine_access_key or os.getenv("PV_ACCESS_KEY")):
            notes.append("WARNING: PV_ACCESS_KEY missing — voice loop will fail to start.")

    bridge_names = [n for n, on in (("Telegram", telegram), ("Discord", discord), ("LINE", line)) if on]
    for n in bridge_names:
        notes.append(f"{n} bot: will start after server is ready")
    suffix = " + ".join(bridge_names) if bridge_names else ("Voice" if voice else "")
    _print_banner("Yumi Server" + (f" + {suffix}" if suffix else ""), _server_banner_rows(config), notes)
    _print_lan_codes()

    server_proc = subprocess.Popen([sys.executable, "-m", "yumi.core.api"], env=server_env)
    local_url = "http://127.0.0.1:8000"
    bridge_procs: list[subprocess.Popen] = []
    try:
        if not _wait_for_server_health(local_url, timeout=90):
            print("\n  Yumi server did not become healthy in time.\n")
            return
        os.environ["YUMI_SERVER_URL"] = local_url

        base_env = _subprocess_env_ensure_platform_tokens()
        base_env["YUMI_SERVER_URL"] = local_url

        def _spawn_bot(module: str, fn: str, extra_env: dict[str, str]) -> None:
            env = dict(base_env)
            env.update({k: v for k, v in extra_env.items() if v})
            bridge_procs.append(subprocess.Popen([sys.executable, "-c", f"from {module} import {fn}; {fn}()"], env=env))

        if telegram:
            _spawn_bot(
                "yumi.telegram.bot", "run_telegram_bot_sync", {"TELEGRAM_BOT_TOKEN": get_telegram_bot_token() or ""}
            )
        if discord:
            _spawn_bot("yumi.discord.bot", "run_discord_bot_sync", {"DISCORD_BOT_TOKEN": get_discord_bot_token() or ""})
        if line:
            _spawn_bot(
                "yumi.line.server",
                "run_line_bot_sync",
                {
                    "LINE_CHANNEL_SECRET": get_line_channel_secret() or "",
                    "LINE_CHANNEL_ACCESS_TOKEN": get_line_channel_access_token() or "",
                },
            )

        if bridge_names:
            print(f"  {' + '.join(bridge_names)} running (Ctrl+C stops the server and all bridges)\n")
        server_proc.wait()
    except KeyboardInterrupt:
        print("\n  Shutting down Yumi.\n")
    finally:
        for p in bridge_procs:
            p.terminate()
        server_proc.terminate()
        for p in [*bridge_procs, server_proc]:
            try:
                p.wait(timeout=15)
            except subprocess.TimeoutExpired:
                p.kill()


def run_server_with_telegram() -> None:
    run_server_with_bridges(telegram=True)


def run_server_with_voice() -> None:
    run_server_with_bridges(voice=True)


def run_server_with_telegram_and_voice() -> None:
    run_server_with_bridges(telegram=True, voice=True)


def run_telegram_standalone() -> None:
    """Run only the Telegram bot; connect to the configured local/LAN Yumi API."""
    if not _prompt_telegram_bot_token_if_missing():
        sys.exit(1)

    env = prepare_client_environment("chat")
    target = env.get("YUMI_SERVER_URL", SERVER_URL)
    _print_banner("Yumi Telegram", [("Backend:", target), ("Mode:", "direct")])

    if not is_server_running(server_health_url(target)):
        print("\n  Yumi server is not running. Start it first with: yumi --server\n")
        sys.exit(1)

    os.environ.update(env)

    from yumi.telegram.bot import run_telegram_bot_sync

    run_telegram_bot_sync()


def run_server_with_discord() -> None:
    run_server_with_bridges(discord=True)


def run_discord_standalone() -> None:
    """Run only the Discord bot; connect to the configured local/LAN Yumi API."""
    if not _prompt_discord_bot_token_if_missing():
        sys.exit(1)

    env = prepare_client_environment("chat")
    target = env.get("YUMI_SERVER_URL", SERVER_URL)
    _print_banner("Yumi Discord", [("Backend:", target), ("Mode:", "direct")])

    if not is_server_running(server_health_url(target)):
        print("\n  Yumi server is not running. Start it first with: yumi --server\n")
        sys.exit(1)

    os.environ.update(env)

    from yumi.discord.bot import run_discord_bot_sync

    run_discord_bot_sync()


def run_server_with_line() -> None:
    run_server_with_bridges(line=True)


def run_line_standalone() -> None:
    """Run only the LINE webhook server; core API must be reachable (like --telegram)."""
    if not _prompt_line_credentials_if_missing():
        sys.exit(1)

    env = prepare_client_environment("chat")
    target = env.get("YUMI_SERVER_URL", SERVER_URL)
    _print_banner("Yumi LINE", [("Backend:", target), ("Mode:", "direct")])

    if not is_server_running(server_health_url(target)):
        print("\n  Yumi server is not running. Start it first with: yumi --server\n")
        sys.exit(1)

    os.environ.update(env)
    ls = get_line_channel_secret()
    lt = get_line_channel_access_token()
    if ls and not (os.environ.get("LINE_CHANNEL_SECRET") or "").strip():
        os.environ["LINE_CHANNEL_SECRET"] = ls
    if lt and not (os.environ.get("LINE_CHANNEL_ACCESS_TOKEN") or "").strip():
        os.environ["LINE_CHANNEL_ACCESS_TOKEN"] = lt

    from yumi.line.server import run_line_bot_sync

    run_line_bot_sync()


# ── ui ──


def _reflex_ui_root() -> str:
    """Directory of the Reflex app (``yumi/ui``, contains ``rxconfig.py``)."""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ui")


def run_ui():
    env = prepare_client_environment("ui")

    if not is_server_running(server_health_url(env.get("YUMI_SERVER_URL"))):
        print("\n  Yumi server is not running. Start it first with: yumi --server\n")
        sys.exit(1)

    lan_ip = _get_lan_ip()

    rows: list[tuple[str, str]] = [
        ("Local:", f"http://localhost:{UI_FRONTEND_PORT}"),
    ]
    if lan_ip:
        rows.append(("Network:", f"http://{lan_ip}:{UI_FRONTEND_PORT}"))
        env["YUMI_UI_API_HOST"] = lan_ip
    rows.append(("Backend:", env.get("YUMI_SERVER_URL", SERVER_URL)))

    _print_banner("Yumi UI", rows)

    subprocess.run([sys.executable, "-m", "reflex", "run"], cwd=_reflex_ui_root(), env=env)


# ── chat ──


def run_chat():
    env = prepare_client_environment("chat")

    if not is_server_running(server_health_url(env.get("YUMI_SERVER_URL"))):
        print("\n  Yumi server is not running. Start it first with: yumi --server\n")
        sys.exit(1)

    target = env.get("YUMI_SERVER_URL", SERVER_URL)
    _print_banner("Yumi Chat", [("Server:", target), ("Mode:", "direct")])

    subprocess.run([sys.executable, "-m", "yumi.chat"], env=env)


# ── edge ──


def _parse_edge_langs(langs: list[str] | None) -> list[str] | None:
    """Normalize ``--lang`` from argparse (repeatable and/or comma-separated)."""
    if not langs:
        return None
    out: list[str] = []
    for s in langs:
        for part in s.split(","):
            p = part.strip().lower()
            if p:
                out.append(p)
    seen: set[str] = set()
    unique: list[str] = []
    for x in out:
        if x not in seen:
            seen.add(x)
            unique.append(x)
    return unique


def _read_env_connection_code(env_path: str) -> str:
    """Read YUMI_CONNECTION_CODE value from a .env file (empty string if unset)."""
    if not os.path.isfile(env_path):
        return ""
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("YUMI_CONNECTION_CODE="):
                return line.split("=", 1)[1].strip()
    return ""


_EDGE_LANG_CHOICES = (
    "python",
    "swift",
    "typescript",
    "cpp",
    "ue5",
    "go",
    "java",
    "csharp",
    "rust",
    "kotlin",
    "dart",
)


def _set_env_var(env_path: str, key: str, value: str) -> None:
    """Set ``KEY=value`` in an existing/created .env file (replace or append)."""
    line = f"{key}={value}"
    if not os.path.isfile(env_path):
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(line + "\n")
        return
    with open(env_path, "r", encoding="utf-8") as f:
        content = f.read()
    if f"{key}=" in content:
        content = "\n".join(line if ln.startswith(f"{key}=") else ln for ln in content.splitlines()) + "\n"
    else:
        content = content.rstrip("\n") + f"\n{line}\n"
    with open(env_path, "w", encoding="utf-8") as f:
        f.write(content)


def _prompt_edge_languages() -> list[str] | None:
    """Interactive language picker. Returns a normalized list, or None for all."""
    print("  Which language(s) for this edge?")
    print("  Options: " + ", ".join(_EDGE_LANG_CHOICES))
    raw = input("  Languages (comma-separated, Enter = all): ").strip()
    return _parse_edge_langs([raw]) if raw else None


def _prompt_edge_name() -> str:
    """Ask for a unique edge name (defaults to the hostname)."""
    default = socket.gethostname() or "my-edge"
    print("  Each edge needs a UNIQUE name — it routes tools to this device.")
    raw = input(f"  Edge name [{default}]: ").strip()
    return raw or default


def run_edge(lang: str | list[str] | None = None, edge_name: str | None = None):
    workspace = os.getcwd()
    interactive = sys.stdin.isatty()

    # When --lang wasn't given, let an interactive user pick the language(s).
    if lang is None and interactive:
        lang = _prompt_edge_languages()

    rows = [("Workspace:", workspace)]
    if lang:
        if isinstance(lang, list):
            rows.append(("Languages:", ", ".join(lang)))
        else:
            rows.append(("Language:", lang))
    else:
        rows.append(
            (
                "Language:",
                "all (python, swift, typescript, cpp, ue5, go, java, csharp, rust, kotlin, dart)",
            )
        )
    _print_banner("Yumi Edge", rows)

    try:
        created = init_workspace(workspace, lang=lang)
    except ValueError as exc:
        print(f"  Error: {exc}\n")
        return

    if created:
        print("  Workspace initialized.\n")
    else:
        print("  Workspace OK.\n")

    env_path = os.path.join(workspace, "yumi_tools", ".env")

    # Edge name (its unique identity). Prompt when not given and interactive,
    # then persist as EDGE_NAME so the scaffolded edge defaults to a unique name.
    if edge_name is None and interactive:
        edge_name = _prompt_edge_name()
    if edge_name:
        _set_env_var(env_path, "EDGE_NAME", edge_name)
        print(f"  Edge name: {edge_name}  (saved as EDGE_NAME in yumi_tools/.env)")

    existing_code = _read_env_connection_code(env_path)

    if existing_code:
        masked = existing_code[:8] + "..." + existing_code[-4:] if len(existing_code) > 12 else existing_code
        print(f"  Connection code: {masked}")
    else:
        code = input("  Enter a connection code (LAN yumi-lan_...), or press Enter to skip: ").strip()
        if code:
            _write_connection_code(env_path, code)
            if _is_lan_code(code):
                try:
                    server_url = parse_lan_code(code)
                    print(f"  Connection code saved (LAN -> {server_url})")
                except ValueError as exc:
                    print(f"  Invalid connection code: {exc}")
            else:
                print("  Connection code saved.")
        else:
            print("  Skipped. Set YUMI_CONNECTION_CODE in yumi_tools/.env later.")

    if lang is None:
        effective: set[str] | None = None
    elif isinstance(lang, str):
        effective = {lang.lower().strip()}
    else:
        effective = set(lang)

    print()
    print("  -- Next steps --")
    print()

    if effective is None or "python" in effective:
        print("  [Python]")
        print("  1. Read yumi_tools/python/README.md")
        print("  2. pip install websockets")
        print("  3. Edit yumi_tools/python/yumi_setup.py")
        print("     Import your functions and register them with agent.register()")
        print("  4. In your main program:")
        print("     from yumi_tools.python.yumi_setup import init_yumi")
        print("     init_yumi()")
        print()

    if effective is None or "swift" in effective:
        print("  [Swift]")
        print("  1. Read yumi_tools/swift/README.md (local package vs same-target)")
        print("  2. Add local package: yumi_tools/swift/YumiSDK (has Package.swift)")
        print("  3. Edit YumiSetup.swift: set yumiConnectionCode / yumiEdgeName, call initYumi()")
        print()

    if effective is None or "typescript" in effective:
        print("  [TypeScript / JavaScript]")
        print("  1. Read yumi_tools/typescript/README.md")
        print("  2. cd yumi_tools/typescript/yumi_sdk && npm install")
        print("  3. Edit yumiSetup.ts: set YUMI_CONNECTION_CODE / YUMI_EDGE_NAME")
        print("  4. In your app:")
        print('     import { initYumi } from "./yumi_tools/typescript/yumiSetup";')
        print("     initYumi();")
        print()

    if effective is None or "cpp" in effective:
        print("  [C / C++]")
        print("  1. Read yumi_tools/cpp/README.md")
        print("  2. In your CMakeLists.txt:")
        print("     add_subdirectory(yumi_tools/cpp/YumiSDK)")
        print("     target_link_libraries(your_app PRIVATE yumi_sdk)")
        print("  3. Edit yumi_setup.cpp: set YUMI_CONNECTION_CODE / YUMI_EDGE_NAME")
        print("  4. Call initYumi() in your main()")
        print()

    if effective is None or "ue5" in effective:
        print("  [Unreal Engine 5]")
        print("  1. Read yumi_tools/ue5/README.md")
        print("  2. Copy YumiSDK/ module into your project's Source/ directory")
        print('  3. Add "YumiSDK" to your .Build.cs PublicDependencyModuleNames')
        print("  4. Edit YumiSetup.cpp: set connection code / edge name")
        print()

    if effective is None or "go" in effective:
        print("  [Go]")
        print("  1. Read yumi_tools/go/README.md")
        print("  2. Add to your go.mod:")
        print("     require yumi_sdk v0.0.0")
        print("     replace yumi_sdk => ./yumi_tools/go/yumi_sdk")
        print("  3. Edit yumi_setup.go: set yumiConnectionCode / yumiEdgeName")
        print("  4. Call InitYumi() in your main()")
        print()

    if effective is None or "java" in effective:
        print("  [Java]")
        print("  1. Read yumi_tools/java/README.md")
        print("  2. cd yumi_tools/java/yumi_sdk && mvn install")
        print("     (or copy io.yumi sources into your project)")
        print("  3. Edit YumiSetup.java: set YUMI_CONNECTION_CODE / YUMI_EDGE_NAME")
        print("  4. Call YumiSetup.initYumi() in your main()")
        print()

    if effective is None or "rust" in effective:
        print("  [Rust]")
        print("  1. Read yumi_tools/rust/README.md")
        print("  2. cd yumi_tools/rust && cargo run")
        print("  3. Edit src/yumi_setup.rs: register tools, set edge name / connection code")
        print()

    if effective is None or "kotlin" in effective:
        print("  [Kotlin]")
        print("  1. Read yumi_tools/kotlin/README.md")
        print("  2. cd yumi_tools/kotlin && gradle run (or ./gradlew run)")
        print("  3. Edit YumiSetup.kt under io.yumi.edge")
        print()

    if effective is None or "dart" in effective:
        print("  [Dart]")
        print("  1. Read yumi_tools/dart/README.md")
        print("  2. cd yumi_tools/dart && dart pub get && dart run")
        print("  3. Edit lib/yumi_setup.dart")
        print()


_RUN_EDGE_COMMANDS: dict[str, tuple[list[str], str, str, str]] = {
    "python": (
        [sys.executable, "-m", "yumi_tools.python.yumi_setup"],
        ".",
        os.path.join("yumi_tools", "python", "yumi_setup.py"),
        "Run the generated Python standalone edge.",
    ),
    "typescript": (
        ["npx", "tsx", "yumiSetup.ts"],
        os.path.join("yumi_tools", "typescript"),
        os.path.join("yumi_tools", "typescript", "yumiSetup.ts"),
        "Run the generated TypeScript standalone edge.",
    ),
    "go": (
        ["go", "run", "."],
        os.path.join("yumi_tools", "go"),
        os.path.join("yumi_tools", "go", "main.go"),
        "Run the generated Go standalone edge.",
    ),
    "rust": (
        ["cargo", "run"],
        os.path.join("yumi_tools", "rust"),
        os.path.join("yumi_tools", "rust", "src", "main.rs"),
        "Run the generated Rust standalone edge.",
    ),
    "kotlin": (
        ["gradle", "run"],
        os.path.join("yumi_tools", "kotlin"),
        os.path.join("yumi_tools", "kotlin", "src", "main", "kotlin", "io", "yumi", "edge", "Main.kt"),
        "Run the generated Kotlin standalone edge.",
    ),
    "dart": (
        ["dart", "run"],
        os.path.join("yumi_tools", "dart"),
        os.path.join("yumi_tools", "dart", "bin", "yumi_edge.dart"),
        "Run the generated Dart standalone edge.",
    ),
}


def _available_run_edge_langs(workspace: str) -> list[str]:
    available: list[str] = []
    for lang_key, (_, _rel_cwd, marker, _) in _RUN_EDGE_COMMANDS.items():
        if os.path.isfile(os.path.join(workspace, marker)):
            available.append(lang_key)
    return available


def _prompt_run_edge_language(available: list[str]) -> str:
    print("  Which standalone edge should run?")
    print("  Options: " + ", ".join(available))
    while True:
        raw = input("  Language: ").strip().lower()
        if raw in available:
            return raw
        print("  Pick one of: " + ", ".join(available))


def run_edge_standalone(lang: str | list[str] | None = None) -> None:
    """Run a generated standalone Edge template from the current workspace."""
    workspace = os.getcwd()
    selected = _parse_edge_langs([lang] if isinstance(lang, str) else lang)
    available = _available_run_edge_langs(workspace)

    if not os.path.isdir(os.path.join(workspace, "yumi_tools")):
        print("  No yumi_tools/ directory found. Create one first with: yumi --edge")
        return

    if selected:
        unsupported = [item for item in selected if item not in _RUN_EDGE_COMMANDS]
        if unsupported:
            print(
                "  Standalone run is not wired for: "
                + ", ".join(unsupported)
                + ". Embed that SDK in your app, or run it with its language guide."
            )
            return
        missing = [item for item in selected if item not in available]
        if missing:
            print(
                "  Template not found for: " + ", ".join(missing) + ". Generate it first with `yumi --edge --lang ...`."
            )
            return
        if len(selected) > 1:
            print("  Choose one language for --run-edge, for example: yumi --run-edge --lang python")
            return
        lang_key = selected[0]
    else:
        if not available:
            print("  No runnable standalone Edge template found under yumi_tools/.")
            print("  Try: yumi --edge --lang python")
            return
        if len(available) == 1 or not sys.stdin.isatty():
            if len(available) > 1:
                print("  Multiple standalone edges found: " + ", ".join(available))
                print("  Choose one with: yumi --run-edge --lang python")
                return
            lang_key = available[0]
        else:
            lang_key = _prompt_run_edge_language(available)

    cmd, rel_cwd, _marker, note = _RUN_EDGE_COMMANDS[lang_key]
    cwd = workspace if rel_cwd == "." else os.path.join(workspace, rel_cwd)
    rows = [
        ("Workspace:", workspace),
        ("Language:", lang_key),
        ("Command:", " ".join(cmd)),
    ]
    _print_banner("Yumi Edge Runner", rows, [note, "Press Ctrl+C to stop the edge."])
    try:
        subprocess.run(cmd, cwd=cwd, env=os.environ.copy())
    except FileNotFoundError:
        print(f"  Could not find `{cmd[0]}` on PATH. Install the {lang_key} toolchain, then try again.")


def _write_connection_code(env_path: str, code: str) -> None:
    """Write the connection code into an existing .env file."""
    if os.path.isfile(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "YUMI_CONNECTION_CODE=" in content:
            lines = content.splitlines()
            new_lines = []
            for line in lines:
                if line.startswith("YUMI_CONNECTION_CODE="):
                    new_lines.append(f"YUMI_CONNECTION_CODE={code}")
                else:
                    new_lines.append(line)
            content = "\n".join(new_lines) + "\n"
        else:
            content += f"\nYUMI_CONNECTION_CODE={code}\n"
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(content)
    else:
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(f"YUMI_CONNECTION_CODE={code}\n")


# ── demo ──


def _run_demo():
    _print_banner(
        "Yumi Demo Suite",
        [
            ("App windows:", "Smart Home + Planner (schedule)"),
            ("Mode:", "Two independent edge apps"),
        ],
        notes=[
            "Keep `yumi --server` running in another terminal, or enter a LAN code below.",
            "After the windows open, use `yumi --chat` or `yumi --ui` to control both.",
            "Each window connects as its own edge host with its own tools.",
            "One message can trigger visible changes in both apps at once.",
        ],
    )

    code: str | None = None

    if is_server_running(server_health_url()):
        print("  Local server detected at http://127.0.0.1:8000")
    else:
        code = _prompt_connection_code("Enter a LAN connection code (yumi-lan_...), or press Enter for localhost: ")

    from yumi.demo.launcher import run_demo_suite

    run_demo_suite(connection_code=code)


# ── cleanup ──


def run_cleanup() -> None:
    print()
    print("  This will remove Yumi user data from this machine:")
    print("  - ~/.yumi/config.json")
    print("  - ~/.yumi/memory/")
    print()
    print("  Ollama and Ollama model files will not be affected.")
    confirm = input("  Type 'delete' to continue: ").strip().lower()
    if confirm != "delete":
        print("  Cleanup cancelled.")
        return

    removed_paths = cleanup_user_data()
    print()
    if removed_paths:
        print("  Removed:")
        for path in removed_paths:
            print(f"    - {path}")
    else:
        print("  No Yumi user data was found.")
    print()


def run_cleanup_memory() -> None:
    print()
    print("  This will remove Yumi memory data from this machine:")
    print("  - ~/.yumi/memory/")
    print("  - legacy memory under yumi/core/memories/.lancedb (if present)")
    print()
    print("  Saved model settings, prompts, and connection codes will be kept.")
    confirm = input("  Type 'delete' to continue: ").strip().lower()
    if confirm != "delete":
        print("  Memory cleanup cancelled.")
        return

    removed_paths = cleanup_memory_data()
    print()
    if removed_paths:
        print("  Removed:")
        for path in removed_paths:
            print(f"    - {path}")
    else:
        print("  No Yumi memory data was found.")
    print()


# ── client environment ──


def prepare_client_environment(scope: str) -> dict:
    """Return an env dict pointing at a reachable local/LAN Yumi API."""
    env = os.environ.copy()
    configured_server_url = env.get("YUMI_SERVER_URL", SERVER_URL)

    if scope in {"chat", "ui"} and is_server_running(server_health_url(configured_server_url)):
        return env

    if scope == "edge":
        return env

    saved_code = get_saved_connection_code()
    if saved_code and _is_lan_code(saved_code):
        try:
            direct_url = parse_lan_code(saved_code)
        except ValueError:
            direct_url = None
        if direct_url and is_server_running(server_health_url(direct_url)):
            env["YUMI_SERVER_URL"] = direct_url
            masked = saved_code[:8] + "..." + saved_code[-4:] if len(saved_code) > 12 else saved_code
            print(f"  Using saved LAN code ({masked})")
            return env

    print(f"  No reachable Yumi server at {configured_server_url}.")
    join_code = input("  Paste a Yumi LAN code (yumi-lan_...): ").strip()
    if not join_code:
        raise SystemExit("  Connection code is required.")
    if not _is_lan_code(join_code):
        raise SystemExit("  Only LAN codes are supported in OSS.")
    try:
        direct_url = parse_lan_code(join_code)
    except ValueError as exc:
        raise SystemExit(f"  Invalid LAN code: {exc}") from exc
    if not is_server_running(server_health_url(direct_url)):
        raise SystemExit(f"  LAN server not reachable at {direct_url}.")
    env["YUMI_SERVER_URL"] = direct_url
    save_connection_code(join_code)
    print("  Connected. Connection code saved for next time.")
    return env


def run_tool_routing_config(args) -> None:
    """Show or update edge tool routing settings in ~/.yumi/config.json."""

    if args.enable_edge_tool_routing and args.disable_edge_tool_routing:
        raise SystemExit("  Use either --enable-edge-tool-routing or --disable-edge-tool-routing, not both.")

    config = load_saved_model_config()
    changed = False

    if args.edge_tools_limit is not None:
        if args.edge_tools_limit < 0 or args.edge_tools_limit > 200:
            raise SystemExit("  --edge-tools-limit must be between 0 and 200.")
        config.edge_tools_retrieval_limit = args.edge_tools_limit
        changed = True

    if args.enable_edge_tool_routing:
        config.edge_tools_enable_dynamic_routing = True
        changed = True
    elif args.disable_edge_tool_routing:
        config.edge_tools_enable_dynamic_routing = False
        changed = True

    if changed:
        save_model_config(config)
        print(f"  Tool routing settings saved to {CONFIG_PATH}")

    effective = load_model_config()
    print()
    print("  Yumi tool routing")
    print(f"  Edge dynamic routing: {'enabled' if effective.edge_tools_enable_dynamic_routing else 'disabled'}")
    print(f"  Edge tools per turn:  {effective.edge_tools_retrieval_limit}")
    print("  Core tools:           always loaded when enabled")
    print()


def run_config_file() -> None:
    """Create/update ~/.yumi/config.json with all known fields and open it."""

    ensure_full_model_config_file()
    print()
    print(f"  Yumi config written to: {CONFIG_PATH}")
    if _open_path_with_default_app(CONFIG_PATH):
        print("  Opened config file in your default editor/app.")
    else:
        print("  Could not auto-open it; open the path above manually.")
    print()
    print("  Edit this one file for persistent settings. Environment variables still override it at runtime.")
    print()


def _open_path_with_default_app(path: Path) -> bool:
    """Best-effort open using the OS default app without blocking Yumi."""
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        elif os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return True
    except Exception:
        return False
