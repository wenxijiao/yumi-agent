"""Smart Home demo package — run with ``python -m yumi.demo.smart_home`` or ``yumi --demo``."""

from __future__ import annotations


def run_demo(connection_code: str | None = None) -> None:
    """Delegate to ``__main__`` so ``init_yumi`` lives only in the process entrypoint."""
    from yumi.demo.smart_home.__main__ import run_demo as _run_demo_entry

    _run_demo_entry(connection_code)


__all__ = ["run_demo"]
