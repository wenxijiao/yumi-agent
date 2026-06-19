"""Concrete :class:`~yumi.cli.registry.Command` implementations.

Each Command is a thin shell around the existing ``run_*`` helper functions
in :mod:`yumi.cli`. The split exists so adding / removing / re-ordering
commands is a one-line ``registry.add(...)`` change instead of a four-place
edit across :func:`main`.

The composition rules between ``--server`` / ``--telegram`` / ``--discord`` /
``--line`` are enforced here too:

* ``ServerCommand`` runs as ``server`` / ``server_with_telegram`` /
  ``server_with_discord`` / ``server_with_line`` based on the modifier flags.
* ``TelegramStandaloneCommand`` / ``DiscordStandaloneCommand`` /
  ``LineStandaloneCommand`` only fire when ``--server`` is absent.
* :func:`validate_cross_command_flags` rejects forbidden combinations (e.g.
  ``--telegram + --line``) before any command runs.
"""

from __future__ import annotations

import argparse

from yumi.cli.registry import Command, CommandRegistry

# ── server-family (with optional --telegram / --line modifiers) ─────────────


class ServerCommand(Command):
    name = "server"

    def register(self, parser, mutex_group):
        mutex_group.add_argument("--server", action="store_true", help="Run the Yumi backend server")

    def matches(self, args):
        return bool(args.server)

    def run(self, args):
        from yumi.cli import (
            run_server,
            run_server_with_discord,
            run_server_with_line,
            run_server_with_telegram,
            run_server_with_telegram_and_voice,
            run_server_with_voice,
        )

        if args.telegram and getattr(args, "voice", False):
            run_server_with_telegram_and_voice()
        elif args.telegram:
            run_server_with_telegram()
        elif getattr(args, "discord", False):
            run_server_with_discord()
        elif args.line:
            run_server_with_line()
        elif getattr(args, "voice", False):
            run_server_with_voice()
        else:
            run_server()


class TelegramStandaloneCommand(Command):
    name = "telegram"

    def register(self, parser, mutex_group):
        # ``--telegram`` doubles as a modifier for ``--server``, so it lives
        # outside the mutex group; ``ServerCommand.run`` handles the combo.
        parser.add_argument(
            "--telegram",
            action="store_true",
            help=("Run Telegram bot (with --server: same process after API starts; alone: client like --chat)"),
        )

    def matches(self, args):
        return bool(args.telegram) and not args.server

    def run(self, args):
        from yumi.cli import run_telegram_standalone

        run_telegram_standalone()


class DiscordStandaloneCommand(Command):
    name = "discord"

    def register(self, parser, mutex_group):
        # ``--discord`` doubles as a modifier for ``--server``, so it lives
        # outside the mutex group; ``ServerCommand.run`` handles the combo.
        parser.add_argument(
            "--discord",
            action="store_true",
            help=("Run Discord bot (with --server: same process after API starts; alone: client like --chat)"),
        )

    def matches(self, args):
        return bool(getattr(args, "discord", False)) and not args.server

    def run(self, args):
        from yumi.cli import run_discord_standalone

        run_discord_standalone()


class LineStandaloneCommand(Command):
    name = "line"

    def register(self, parser, mutex_group):
        parser.add_argument(
            "--line",
            action="store_true",
            help=(
                "Run LINE webhook sidecar (with --server: after API starts;"
                " use YUMI_LINE_INCORE=1 to mount webhook on core instead)"
            ),
        )

    def matches(self, args):
        return bool(args.line) and not args.server

    def run(self, args):
        from yumi.cli import run_line_standalone

        run_line_standalone()


class VoiceModifierCommand(Command):
    """``--voice`` modifier: attach a microphone wake-word loop to ``--server``.

    Like ``--telegram``, this flag lives outside the mutex group and only acts
    as a modifier of ``--server``. There is no standalone mode in v1, so
    :meth:`matches` always returns False.
    """

    name = "voice"

    def register(self, parser, mutex_group):
        parser.add_argument(
            "--voice",
            action="store_true",
            help=(
                "With --server: open a microphone wake-word session (say 'hi yumi'). "
                "Requires pip install yumi-agent[voice,stt] and a Picovoice access key."
            ),
        )

    def matches(self, args):
        return False

    def run(self, args):  # pragma: no cover - modifier-only
        return None


# ── lifecycle / setup commands ─────────────────────────────────────────────


class UICommand(Command):
    name = "ui"

    def register(self, parser, mutex_group):
        mutex_group.add_argument("--ui", action="store_true", help="Open the Yumi web UI")

    def matches(self, args):
        return bool(args.ui)

    def run(self, args):
        from yumi.cli import run_ui

        run_ui()


class ChatCommand(Command):
    name = "chat"

    def register(self, parser, mutex_group):
        mutex_group.add_argument("--chat", action="store_true", help="Start chat in terminal")

    def matches(self, args):
        return bool(args.chat)

    def run(self, args):
        from yumi.cli import run_chat

        run_chat()


class EdgeCommand(Command):
    name = "edge"

    def register(self, parser, mutex_group):
        mutex_group.add_argument("--edge", action="store_true", help="Initialize a Yumi Edge workspace")
        parser.add_argument(
            "--lang",
            action="append",
            dest="langs",
            metavar="LANG",
            default=None,
            help=(
                "Language(s) for --edge (repeatable). "
                "Examples: --lang rust --lang python   or   --lang rust,python. "
                "Default: scaffold all languages."
            ),
        )
        parser.add_argument(
            "--edge-name",
            dest="edge_name",
            default=None,
            metavar="NAME",
            help=(
                "Name for this edge (must be unique across your edges; "
                "default: hostname). With --edge it prefills the scaffold."
            ),
        )

    def matches(self, args):
        return bool(args.edge)

    def run(self, args):
        from yumi.cli import _parse_edge_langs, run_edge

        run_edge(lang=_parse_edge_langs(args.langs), edge_name=args.edge_name)


class DemoCommand(Command):
    name = "demo"

    def register(self, parser, mutex_group):
        mutex_group.add_argument(
            "--demo",
            action="store_true",
            help="Run the Smart Home + Planner (schedule) demo",
        )

    def matches(self, args):
        return bool(args.demo)

    def run(self, args):
        from yumi.cli import _run_demo

        _run_demo()


class SetupCommand(Command):
    name = "setup"

    def register(self, parser, mutex_group):
        mutex_group.add_argument("--setup", action="store_true", help="Configure Yumi models")
        # Non-interactive setup (Docker/CI): pass --provider to skip all prompts.
        parser.add_argument(
            "--provider",
            dest="setup_provider",
            default=None,
            help="With --setup: chat provider (ollama/openai/claude/gemini/deepseek), non-interactive",
        )
        parser.add_argument(
            "--model",
            dest="setup_model",
            default=None,
            help="With --setup: chat model (default: provider's recommended)",
        )
        parser.add_argument(
            "--api-key", dest="setup_api_key", default=None, help="With --setup: API key for the chosen cloud provider"
        )
        parser.add_argument(
            "--embedding-provider",
            dest="setup_embed_provider",
            default=None,
            help="With --setup: embedding provider (ollama/openai/gemini); omit to disable embeddings",
        )
        parser.add_argument(
            "--embedding-model", dest="setup_embed_model", default=None, help="With --setup: embedding model name"
        )
        parser.add_argument(
            "--no-embeddings",
            dest="setup_no_embed",
            action="store_true",
            help="With --setup: disable embeddings (long-term memory + dynamic tool routing off)",
        )

    def matches(self, args):
        return bool(args.setup)

    def run(self, args):
        provider = getattr(args, "setup_provider", None)
        if provider:
            from yumi.core.features.config import configure_models_noninteractive

            cfg = configure_models_noninteractive(
                provider=provider,
                model=getattr(args, "setup_model", None),
                api_key=getattr(args, "setup_api_key", None),
                embedding_provider=getattr(args, "setup_embed_provider", None),
                embedding_model=getattr(args, "setup_embed_model", None),
                no_embeddings=getattr(args, "setup_no_embed", False),
            )
            emb = f"{cfg.embedding_provider}/{cfg.embedding_model}" if cfg.embedding_model else "off"
            print(f"Saved: chat={cfg.chat_provider}/{cfg.chat_model}, embedding={emb}")
            return

        from yumi.cli import run_model_setup

        run_model_setup(force=True)


class ConfigCommand(Command):
    name = "config"

    def register(self, parser, mutex_group):
        mutex_group.add_argument(
            "--config",
            action="store_true",
            help="Create/show the full ~/.yumi/config.json settings file",
        )

    def matches(self, args):
        return bool(args.config)

    def run(self, args):
        from yumi.cli import run_config_file

        run_config_file()


class ToolRoutingCommand(Command):
    name = "tool-routing"

    def register(self, parser, mutex_group):
        mutex_group.add_argument(
            "--tool-routing",
            action="store_true",
            help="Show or configure edge tool routing",
        )
        parser.add_argument(
            "--edge-tools-limit",
            type=int,
            default=None,
            metavar="N",
            help="With --tool-routing: edge tool schemas exposed per turn (0-200, default 20)",
        )
        parser.add_argument(
            "--enable-edge-tool-routing",
            action="store_true",
            help="With --tool-routing: rank and cap edge tools per turn",
        )
        parser.add_argument(
            "--disable-edge-tool-routing",
            action="store_true",
            help="With --tool-routing: pass all enabled edge tools through",
        )

    def matches(self, args):
        return bool(args.tool_routing)

    def run(self, args):
        from yumi.cli import run_tool_routing_config

        run_tool_routing_config(args)


class CleanupCommand(Command):
    name = "cleanup"

    def register(self, parser, mutex_group):
        mutex_group.add_argument("--cleanup", action="store_true", help="Delete Yumi user data")

    def matches(self, args):
        return bool(args.cleanup)

    def run(self, args):
        from yumi.cli import run_cleanup

        run_cleanup()


class CleanupMemoryCommand(Command):
    name = "cleanup-memory"

    def register(self, parser, mutex_group):
        mutex_group.add_argument(
            "--cleanup-memory",
            action="store_true",
            help="Delete Yumi memory only",
        )

    def matches(self, args):
        return bool(args.cleanup_memory)

    def run(self, args):
        from yumi.cli import run_cleanup_memory

        run_cleanup_memory()


# ── cross-command flag validation ──────────────────────────────────────────


_NON_SERVER_BASE_FLAGS = ("ui", "chat", "edge", "demo", "setup", "config", "cleanup", "cleanup_memory", "tool_routing")


def _format_non_server_flag_list() -> str:
    """Render the flag list as a CLI-formatted slash-joined string."""
    return "/".join(f"--{flag.replace('_', '-')}" for flag in _NON_SERVER_BASE_FLAGS)


def validate_cross_command_flags(args: argparse.Namespace) -> str | None:
    """Reject combinations of flags that span multiple commands.

    Per-command checks live in each :class:`Command.validate`. This helper
    handles the combinations the OSS CLI has historically rejected:

    * any two of ``--telegram`` / ``--discord`` / ``--line`` together,
    * ``--telegram`` / ``--discord`` / ``--line`` combined with any non-server command,
    * ``--tool-routing``-only flags used without ``--tool-routing``.
    """
    bridge_flags = [f for f in ("telegram", "discord", "line") if getattr(args, f, False)]
    if len(bridge_flags) > 1:
        return "Use only one of --telegram / --discord / --line, not several."

    if not getattr(args, "tool_routing", False) and (
        getattr(args, "edge_tools_limit", None) is not None
        or getattr(args, "enable_edge_tool_routing", False)
        or getattr(args, "disable_edge_tool_routing", False)
    ):
        return "Use --edge-tools-limit/--enable-edge-tool-routing/--disable-edge-tool-routing with --tool-routing."

    flag_list = _format_non_server_flag_list()

    if bridge_flags:
        if any(getattr(args, flag, False) for flag in _NON_SERVER_BASE_FLAGS):
            return f"Cannot combine --telegram/--discord/--line with {flag_list}."

    if getattr(args, "voice", False):
        if getattr(args, "discord", False):
            return "Cannot combine --voice with --discord."
        if getattr(args, "line", False):
            return "Cannot combine --voice with --line."
        if any(getattr(args, flag, False) for flag in _NON_SERVER_BASE_FLAGS):
            return f"Cannot combine --voice with {flag_list}."
        if not getattr(args, "server", False):
            return "--voice is a modifier; it must be combined with --server."
    return None


# ── built-in command set ───────────────────────────────────────────────────


def build_default_registry() -> CommandRegistry:
    """Return the OSS-default :class:`CommandRegistry`.

    Order is significant only for ``--help`` output (commands are listed in
    insertion order). Enterprise builds may extend the registry via the
    ``AdminCli`` plugin port without altering this file.
    """
    registry = CommandRegistry()
    # mutex commands first so their primary flags appear together in --help
    registry.add(ServerCommand())
    registry.add(UICommand())
    registry.add(ChatCommand())
    registry.add(EdgeCommand())
    registry.add(DemoCommand())
    registry.add(SetupCommand())
    registry.add(ConfigCommand())
    registry.add(ToolRoutingCommand())
    registry.add(CleanupCommand())
    registry.add(CleanupMemoryCommand())
    # standalone commands that double as modifier flags
    registry.add(TelegramStandaloneCommand())
    registry.add(DiscordStandaloneCommand())
    registry.add(LineStandaloneCommand())
    registry.add(VoiceModifierCommand())
    return registry


__all__ = [
    "ChatCommand",
    "CleanupCommand",
    "CleanupMemoryCommand",
    "ConfigCommand",
    "DemoCommand",
    "DiscordStandaloneCommand",
    "EdgeCommand",
    "LineStandaloneCommand",
    "ServerCommand",
    "SetupCommand",
    "TelegramStandaloneCommand",
    "ToolRoutingCommand",
    "UICommand",
    "VoiceModifierCommand",
    "build_default_registry",
    "validate_cross_command_flags",
]
