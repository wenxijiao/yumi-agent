"""Unit tests for the CLI command registry and cross-command validation.

Exercises dispatch selection and flag validation without spawning any process
or touching the network.
"""

import argparse
from types import SimpleNamespace

import pytest
from yumi.cli.commands import UICommand, build_default_registry, validate_cross_command_flags


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="yumi")
    build_default_registry().install(parser)
    return parser.parse_args(argv)


def _select_name(argv: list[str]) -> str | None:
    args = _parse(argv)
    cmd = build_default_registry().select(args)
    return cmd.name if cmd else None


@pytest.mark.parametrize(
    "argv,expected",
    [
        (["--server"], "server"),
        (["--discord"], "discord"),
        (["--ui"], "ui"),
        (["--chat"], "chat"),
        (["--edge"], "edge"),
        (["--run-edge"], "run-edge"),
        (["--run_edge"], "run-edge"),
        (["--setup"], "setup"),
        (["--config"], "config"),
    ],
)
def test_select_picks_the_matching_command(argv, expected):
    assert _select_name(argv) == expected


def test_no_flags_selects_nothing():
    assert _select_name([]) is None


def test_multiple_primary_commands_are_rejected():
    err = validate_cross_command_flags(_parse(["--server", "--setup"]))
    assert err and "--server" in err and "--setup" in err


# ── cross-command validation ──


def test_multiple_bridges_with_server_is_valid():
    assert validate_cross_command_flags(_parse(["--server", "--telegram", "--line"])) is None
    assert validate_cross_command_flags(_parse(["--server", "--telegram", "--discord"])) is None


def test_multiple_bridges_without_server_is_rejected():
    err = validate_cross_command_flags(_parse(["--telegram", "--discord"]))
    assert err and "--server" in err


def test_discord_with_server_is_valid():
    assert validate_cross_command_flags(_parse(["--server", "--discord"])) is None


def test_voice_requires_server():
    err = validate_cross_command_flags(_parse(["--voice"]))
    assert err and "--server" in err


def test_voice_with_server_is_valid():
    assert validate_cross_command_flags(_parse(["--server", "--voice"])) is None


def test_edge_tool_flags_require_tool_routing():
    err = validate_cross_command_flags(_parse(["--edge-tools-limit", "5"]))
    assert err and "--tool-routing" in err


def test_plain_server_is_valid():
    assert validate_cross_command_flags(_parse(["--server"])) is None


def test_ui_command_checks_node_before_installing_ui_extra(monkeypatch):
    monkeypatch.setattr("yumi.cli.runners._ensure_ui_node_runtime", lambda: False)
    monkeypatch.setattr(
        "yumi.core.features.config.feature_install.ensure_feature_installed",
        lambda *_args, **_kwargs: pytest.fail("UI extra should not install before Node is ready"),
    )
    monkeypatch.setattr("yumi.cli.run_ui", lambda: pytest.fail("UI should not start before Node is ready"))

    UICommand().run(SimpleNamespace())
