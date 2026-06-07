"""Backward-compatible entry for ``python -m yumi.chat`` (implementation in ``cli.terminal_chat``)."""

from yumi.cli.terminal_chat import main

if __name__ == "__main__":
    main()
