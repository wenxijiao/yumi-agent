"""Command Pattern + registry for the Yumi CLI.

Background
----------
``yumi.cli.main`` used to be a 100-line block of ``if args.server: ... elif
args.ui: ... elif args.chat: ...`` with a separate hand-written pyramid of
mutex validations. Adding a new sub-command meant editing four places
(parser, validation, dispatch, help), and plugin-provided admin commands had
no natural way to inject into that namespace.

This module replaces the dispatch tower with a small Command Pattern:

* :class:`Command` — one CLI sub-command. Knows how to register its flags,
  recognise itself in parsed args, validate, and run.
* :class:`CommandRegistry` — ordered set of commands; mounts every command
  on the same ``argparse`` parser, then picks the one that ``matches`` the
  parsed args.

Core commands live in :mod:`yumi.cli.commands`. Plugins can call
``CommandRegistry.add`` from the ``AdminCli`` plugin port to inject extra
sub-commands without modifying OSS code.
"""

from __future__ import annotations

import argparse
from abc import ABC, abstractmethod
from typing import ClassVar


class Command(ABC):
    """One Yumi CLI sub-command."""

    name: ClassVar[str]
    """Short identifier (used in error messages); typically matches ``--<name>``."""

    @abstractmethod
    def register(
        self,
        parser: argparse.ArgumentParser,
        mutex_group: argparse._MutuallyExclusiveGroup,
    ) -> None:
        """Add this command's flags to ``parser`` / ``mutex_group``.

        Mutex commands (only one of them runs per invocation) add their
        primary flag to ``mutex_group``; modifier flags shared with other
        commands (like ``--telegram``) attach directly to ``parser``.
        """

    @abstractmethod
    def matches(self, args: argparse.Namespace) -> bool:
        """Return True if ``args`` selects this command."""

    def validate(self, args: argparse.Namespace) -> str | None:
        """Optional intra-command validation.

        Return ``None`` if all flag combinations are valid for this command,
        or a human-readable error string otherwise. Cross-command checks
        (e.g. ``--telegram + --line is forbidden``) live in
        :func:`yumi.cli.commands.validate_cross_command_flags`.
        """
        return None

    @abstractmethod
    def run(self, args: argparse.Namespace) -> int | None:
        """Execute the command. Return process exit code (None == 0)."""


class CommandRegistry:
    """Ordered registry of :class:`Command` instances."""

    def __init__(self) -> None:
        self._commands: list[Command] = []

    def add(self, command: Command) -> None:
        """Append ``command`` to the registry."""
        self._commands.append(command)

    def __iter__(self):
        return iter(self._commands)

    def install(self, parser: argparse.ArgumentParser) -> None:
        """Mount every command's flags onto ``parser``.

        Creates one mutex group shared by all mutex commands; modifier flags
        attach directly to ``parser`` via the command's own ``register``.
        """
        mutex_group = parser.add_mutually_exclusive_group()
        for cmd in self._commands:
            cmd.register(parser, mutex_group)

    def select(self, args: argparse.Namespace) -> Command | None:
        """Pick the unique command that ``matches`` ``args``.

        Returns ``None`` if no command applies (caller typically prints help).
        Raises :class:`SystemExit` if more than one matches — that points at
        a registry-level bug, not a user error.
        """
        candidates = [c for c in self._commands if c.matches(args)]
        if len(candidates) > 1:
            names = ", ".join(c.name for c in candidates)
            raise SystemExit(f"  Ambiguous CLI command: {names} (registry bug)")
        return candidates[0] if candidates else None


__all__ = ["Command", "CommandRegistry"]
