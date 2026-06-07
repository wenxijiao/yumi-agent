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

from yumi.cli.runners import (
    _parse_edge_langs,
    _reflex_ui_root,
    _run_demo,
    prepare_client_environment,
    run_chat,
    run_cleanup,
    run_cleanup_memory,
    run_config_file,
    run_edge,
    run_line_standalone,
    run_model_setup,
    run_server,
    run_server_with_line,
    run_server_with_telegram,
    run_server_with_telegram_and_voice,
    run_server_with_voice,
    run_telegram_standalone,
    run_tool_routing_config,
    run_ui,
)
from yumi.logging_config import configure_logging

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
    "run_edge",
    "run_line_standalone",
    "run_model_setup",
    "run_server",
    "run_server_with_line",
    "run_server_with_telegram",
    "run_server_with_telegram_and_voice",
    "run_server_with_voice",
    "run_telegram_standalone",
    "run_tool_routing_config",
    "run_ui",
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

    parser = argparse.ArgumentParser(
        description="Yumi command line interface",
        epilog="OSS edition: local / LAN single-user. Multi-tenant + remote relay live in yumi-enterprise.",
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
