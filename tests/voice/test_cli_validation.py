"""CLI validation: --voice composes with --server, rejects other commands."""

from __future__ import annotations

import argparse

import pytest
from kumi.cli.commands import build_default_registry, validate_cross_command_flags


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    registry = build_default_registry()
    registry.install(parser)
    return parser.parse_args(argv)


def test_voice_alone_without_server_is_rejected():
    args = _parse(["--voice"])
    err = validate_cross_command_flags(args)
    assert err is not None
    assert "--voice" in err


def test_voice_with_server_passes():
    args = _parse(["--server", "--voice"])
    assert validate_cross_command_flags(args) is None


def test_voice_with_telegram_and_server_passes():
    args = _parse(["--server", "--telegram", "--voice"])
    assert validate_cross_command_flags(args) is None


def test_voice_with_ui_is_rejected():
    args = _parse(["--ui", "--voice"])
    err = validate_cross_command_flags(args)
    assert err is not None
    assert "--voice" in err


def test_voice_with_line_is_rejected():
    args = _parse(["--server", "--line", "--voice"])
    err = validate_cross_command_flags(args)
    assert err is not None
    # Either the --voice + non-server or the --voice + --line check fires first;
    # both are valid rejections.
    assert "--voice" in err


@pytest.mark.parametrize("flag", ["--ui", "--chat", "--edge", "--demo", "--setup", "--config", "--cleanup"])
def test_voice_with_non_server_command_rejected(flag):
    args = _parse([flag, "--voice"])
    err = validate_cross_command_flags(args)
    assert err is not None
