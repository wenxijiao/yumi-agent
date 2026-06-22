"""Periodic memory maintenance hook (no-op in OSS).

Plugins that need scheduled compaction or row-level retention can spawn their
own task; the default keeps this as a no-op so the LanceDB store never fights
with itself in single-user mode.
"""

from __future__ import annotations


def start_memory_prune_sweep() -> None:
    """No-op in OSS (kept for backward import compatibility)."""
    return None
