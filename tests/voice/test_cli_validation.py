"""CLI validation: --voice is the one standalone voice entry point."""

from __future__ import annotations

import argparse

import pytest
from yumi.cli.commands import build_default_registry, validate_cross_command_flags


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    registry = build_default_registry()
    registry.install(parser)
    return parser.parse_args(argv)


def test_voice_alone_is_valid():
    args = _parse(["--voice"])
    assert validate_cross_command_flags(args) is None
    assert build_default_registry().select(args).name == "voice"


def test_voice_with_server_is_rejected():
    args = _parse(["--server", "--voice"])
    assert validate_cross_command_flags(args) is not None


def test_voice_with_telegram_and_server_is_rejected():
    assert validate_cross_command_flags(_parse(["--server", "--telegram", "--voice"])) is not None


def test_voice_with_ui_is_rejected():
    args = _parse(["--ui", "--voice"])
    err = validate_cross_command_flags(args)
    assert err is not None
    assert "--voice" in err


def test_voice_with_line_is_rejected():
    assert validate_cross_command_flags(_parse(["--server", "--line", "--voice"])) is not None


@pytest.mark.parametrize("flag", ["--ui", "--chat", "--edge", "--demo", "--setup", "--config", "--cleanup"])
def test_voice_with_non_server_command_rejected(flag):
    args = _parse([flag, "--voice"])
    err = validate_cross_command_flags(args)
    assert err is not None


def test_voice_options_need_voice_command():
    assert validate_cross_command_flags(_parse(["--voice-mode", "nexus"])) == "Voice options require --voice."
