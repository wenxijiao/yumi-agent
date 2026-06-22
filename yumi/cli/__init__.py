"""Yumi CLI entry point.

This package is intentionally thin:

* :func:`main` (here) owns the ``.env`` load, parser construction,
  cross-command validation, and the keyboard-interrupt safety net.
* :mod:`yumi.cli.commands` declares one ``Command`` class per sub-command.
* :mod:`yumi.cli.registry` holds the ``Command`` ABC + ``CommandRegistry``.
* :mod:`yumi.cli.runners` holds the ``run_*`` implementation helpers.

The ``run_*`` helpers are re-exported here so existing call sites
(``from yumi.cli import run_server``) keep working unchanged.
"""

from __future__ import annotations

import argparse
from importlib.metadata import PackageNotFoundError, version

from yumi.cli.runners import (
    _parse_edge_langs,
    _reflex_ui_root,
    _run_demo,
    prepare_client_environment,
    run_chat,
    run_cleanup,
    run_cleanup_memory,
    run_config_file,
    run_discord_standalone,
    run_edge,
    run_edge_standalone,
    run_line_standalone,
    run_model_setup,
    run_server,
    run_server_with_bridges,
    run_server_with_discord,
    run_server_with_line,
    run_server_with_telegram,
    run_server_with_telegram_and_voice,
    run_server_with_voice,
    run_telegram_standalone,
    run_tool_routing_config,
    run_ui,
    setup_messaging_tokens,
)
from yumi.logging_config import configure_logging


def _package_version() -> str:
    """Return the installed package version, with a source-tree fallback."""
    try:
        return version("yumi-agent")
    except PackageNotFoundError:
        from yumi import __version__

        return __version__


def _help_table(title: str, rows: list[tuple[str, str]]) -> str:
    cmd_width = max(len("Command"), *(len(command) for command, _ in rows))
    desc_width = max(len("What it does"), *(len(description) for _, description in rows))
    title_width = cmd_width + desc_width + 3
    if title_width < len(title):
        desc_width += len(title) - title_width
        title_width = len(title)

    border = "+" + "-" * (cmd_width + 2) + "+" + "-" * (desc_width + 2) + "+"
    lines = [
        border,
        f"| {title:<{title_width}} |",
        border,
        f"| {'Command':<{cmd_width}} | {'What it does':<{desc_width}} |",
        border,
    ]
    for command, description in rows:
        lines.append(f"| {command:<{cmd_width}} | {description:<{desc_width}} |")
    lines.append(border)
    return "\n".join(lines)


def _format_cli_help() -> str:
    parts = [
        f"Yumi {_package_version()}",
        "",
        "Use local Ollama or cloud models, then chat through terminal, Web UI, messaging, or voice to control tools exposed by Edge apps.",
        "",
        "Usage:",
        "  yumi [command] [options]",
        "",
        _help_table(
            "Quick Start",
            [
                ("yumi --setup", "Configure provider, model, embeddings, and optional API keys."),
                ("yumi --server", "Start the local backend API at http://127.0.0.1:8000."),
                ("yumi --chat", "Open terminal chat against the running server."),
                ("yumi --ui", "Open the Web UI for chat, tools, and settings."),
            ],
        ),
        "",
        _help_table(
            "Run Locally",
            [
                ("yumi --server", "Run the backend API server."),
                ("  --host ADDR", "Bind address for --server. Default is 127.0.0.1."),
                ("  --port PORT", "Port for --server. Default is 8000."),
                ("yumi --chat", "Start terminal chat."),
                ("yumi --ui", "Start the Web UI."),
                ("yumi --demo", "Run the Smart Home + Planner demo."),
                ('yumi --speak "text"', "Synthesize text with the configured TTS provider."),
            ],
        ),
        "",
        _help_table(
            "Connect Your App",
            [
                ("yumi --edge", "Interactively scaffold Edge templates in the current directory."),
                ("  --lang LANG", "Choose template languages. Repeat or use commas, such as rust,python."),
                ("  --edge-name NAME", "Set a unique display name for this edge device or app."),
                ("yumi --run-edge", "Run a generated standalone Edge template from this workspace."),
                ("  --lang LANG", "Choose which standalone Edge template to run, such as python or go."),
                ("yumi --tool-routing", "Show or configure Edge tool routing."),
                ("  --edge-tools-limit N", "Set how many Edge tool schemas are exposed per turn."),
                ("  --enable-edge-tool-routing", "Rank and cap Edge tool schemas per turn."),
                ("  --disable-edge-tool-routing", "Pass all enabled Edge tools through without routing."),
            ],
        ),
        "",
        _help_table(
            "Setup And Maintenance",
            [
                ("yumi --setup", "Configure models and provider credentials interactively."),
                ("  --provider NAME", "Run setup non-interactively for ollama/openai/claude/gemini/deepseek/grok."),
                ("  --model NAME", "Set the chat model during non-interactive setup."),
                ("  --api-key KEY", "Save the API key for the selected cloud provider."),
                ("  --embedding-provider NAME", "Set the embedding provider during non-interactive setup."),
                ("  --embedding-model NAME", "Set the embedding model during non-interactive setup."),
                ("  --no-embeddings", "Disable embeddings, long-term memory search, and dynamic tool routing."),
                ("yumi --config", "Create or open the full ~/.yumi/config.json settings file."),
                ("yumi --cleanup", "Delete all Yumi user data under ~/.yumi/."),
                ("yumi --cleanup-memory", "Delete saved chat memory and embeddings only."),
            ],
        ),
        "",
        _help_table(
            "Messaging And Voice",
            [
                ("yumi --server --telegram", "Run the API and Telegram bot together."),
                ("yumi --telegram", "Run only the Telegram bot; the API must already be reachable."),
                ("yumi --server --discord", "Run the API and Discord bot together."),
                ("yumi --discord", "Run only the Discord bot; the API must already be reachable."),
                ("yumi --server --line", "Run the API and LINE webhook sidecar together."),
                ("yumi --line", "Run only the LINE webhook server."),
                ("yumi --server --telegram --discord --line", "Run the API with all configured messaging bridges."),
                ("yumi --server --voice", "Attach a microphone wake-word loop to the API server."),
            ],
        ),
        "",
        _help_table(
            "Global Options",
            [
                ("-h, --help", "Show this help page and exit."),
                ("-v, --version", "Show Yumi version and exit."),
            ],
        ),
        "",
        "Notes:",
        "  Expose the server on your LAN only on a trusted network:",
        "    yumi --server --host 0.0.0.0",
        "  Docs: README.md and docs/GETTING_STARTED.md",
        "",
    ]
    return "\n".join(parts)


class _YumiArgumentParser(argparse.ArgumentParser):
    def format_help(self) -> str:
        return _format_cli_help()

    def format_usage(self) -> str:
        return "usage: yumi [command] [options]\n"


__all__ = [
    "_parse_edge_langs",
    "_reflex_ui_root",
    "_run_demo",
    "main",
    "prepare_client_environment",
    "run_chat",
    "run_cleanup",
    "run_cleanup_memory",
    "run_config_file",
    "run_discord_standalone",
    "run_edge",
    "run_edge_standalone",
    "run_line_standalone",
    "run_model_setup",
    "run_server",
    "run_server_with_bridges",
    "run_server_with_discord",
    "run_server_with_line",
    "run_server_with_telegram",
    "run_server_with_telegram_and_voice",
    "run_server_with_voice",
    "run_telegram_standalone",
    "run_tool_routing_config",
    "run_ui",
    "setup_messaging_tokens",
]


def main():
    """CLI entry point (`yumi = "yumi.cli:main"` in pyproject.toml).

    Implementation lives in :mod:`yumi.cli.commands` (one ``Command`` class
    per sub-command), :mod:`yumi.cli.registry`, and :mod:`yumi.cli.runners`.
    This function only owns the .env load, parser construction, cross-command
    validation, and the keyboard-interrupt safety net.
    """
    from yumi.cli.commands import build_default_registry, validate_cross_command_flags
    from yumi.core.platform.env_load import load_yumi_dotenv

    load_yumi_dotenv()

    parser = _YumiArgumentParser(
        prog="yumi",
        usage="yumi [command] [options]",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"yumi {_package_version()}",
        help="Show Yumi version and exit",
    )
    registry = build_default_registry()
    registry.install(parser)

    args = parser.parse_args()
    configure_logging()

    err = validate_cross_command_flags(args)
    if err:
        raise SystemExit(f"  {err}")

    command = registry.select(args)
    if command is None:
        parser.print_help()
        return

    err = command.validate(args)
    if err:
        raise SystemExit(f"  {err}")

    try:
        command.run(args)
    except KeyboardInterrupt:
        print("\n  Shutting down Yumi.\n")


if __name__ == "__main__":
    main()
