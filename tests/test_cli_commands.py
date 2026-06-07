"""Unit tests for the CLI command registry and cross-command validation.

Exercises dispatch selection and flag validation without spawning any process
or touching the network.
"""

import argparse

import pytest
from kumi.cli.commands import build_default_registry, validate_cross_command_flags


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="kumi")
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
        (["--ui"], "ui"),
        (["--chat"], "chat"),
        (["--edge"], "edge"),
        (["--setup"], "setup"),
        (["--config"], "config"),
    ],
)
def test_select_picks_the_matching_command(argv, expected):
    assert _select_name(argv) == expected


def test_no_flags_selects_nothing():
    assert _select_name([]) is None


def test_mutually_exclusive_primary_flags_rejected_by_argparse():
    with pytest.raises(SystemExit):
        _parse(["--server", "--chat"])


# ── cross-command validation ──


def test_telegram_and_line_together_is_rejected():
    err = validate_cross_command_flags(_parse(["--server", "--telegram", "--line"]))
    assert err and "not both" in err


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
