"""Mutable tool enablement and confirmation policy."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ToolPolicy:
    """Tracks runtime tool visibility and confirmation decisions."""

    disabled_tools: set[str] = field(default_factory=set)
    confirmation_tools: set[str] = field(default_factory=set)
    always_allowed_tools: set[str] = field(default_factory=set)
    pending_confirmations: dict[str, object] = field(default_factory=dict)
