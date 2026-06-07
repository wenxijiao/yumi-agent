"""Discover and load plugins via the ``yumi.plugins`` entry-point group."""

from __future__ import annotations

import importlib
import os
from importlib.metadata import EntryPoint, entry_points
from typing import Iterable

from yumi.logging_config import get_logger

_log = get_logger(__name__)
ENTRY_POINT_GROUP = "yumi.plugins"

_loaded: set[str] = set()


def _iter_entry_points() -> Iterable[EntryPoint]:
    try:
        eps = entry_points()
    except Exception:
        return ()
    selected = getattr(eps, "select", None)
    if callable(selected):
        return selected(group=ENTRY_POINT_GROUP)
    return tuple(eps.get(ENTRY_POINT_GROUP, ()))  # pragma: no cover - older Python only


def load_entry_point_plugins() -> list[str]:
    """Import every ``yumi.plugins`` entry-point and call its ``register()`` callable.

    Each entry-point should resolve to either a callable (called with no args)
    or a module that exposes a top-level ``register()`` function.

    Set ``YUMI_DISABLE_PLUGINS=1`` to skip discovery entirely (useful in tests).
    Returns the list of entry-point names that were successfully invoked.
    """
    if os.getenv("YUMI_DISABLE_PLUGINS", "").strip().lower() in ("1", "true", "yes"):
        return []

    invoked: list[str] = []
    for ep in _iter_entry_points():
        if ep.name in _loaded:
            continue
        try:
            target = ep.load()
            if callable(target):
                target()
            elif hasattr(target, "register") and callable(target.register):
                target.register()
            else:
                _log.warning("yumi plugin %s did not expose a register() callable", ep.name)
                continue
            _loaded.add(ep.name)
            invoked.append(ep.name)
            _log.info("loaded yumi plugin: %s", ep.name)
        except Exception:
            _log.exception("failed to load yumi plugin: %s", ep.name)
    return invoked


def load_plugin_module(module_path: str) -> None:
    """Manually load a single plugin by dotted module path (testing convenience)."""
    mod = importlib.import_module(module_path)
    register = getattr(mod, "register", None)
    if callable(register):
        register()
        _loaded.add(module_path)
