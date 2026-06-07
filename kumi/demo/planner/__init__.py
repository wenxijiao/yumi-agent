"""Planner (tkinter) demo — run with ``python -m kumi.demo.planner`` or ``kumi --demo``."""

from __future__ import annotations


def run_demo(connection_code: str | None = None) -> None:
    """Delegate to ``__main__`` so ``init_kumi`` lives only in the process entrypoint."""
    from kumi.demo.planner.__main__ import run_demo as _run_demo_entry

    _run_demo_entry(connection_code)


__all__ = ["run_demo"]
