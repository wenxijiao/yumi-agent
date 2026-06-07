"""Central logging configuration for Kumi (library and CLI).

Set ``KUMI_LOG_LEVEL`` to ``DEBUG``, ``INFO``, ``WARNING``, ``ERROR``, or ``CRITICAL``.
"""

from __future__ import annotations

import logging
import os

_CONFIGURED = False


def configure_logging() -> None:
    """Configure root logging once (idempotent)."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    level_name = os.environ.get("KUMI_LOG_LEVEL", "WARNING").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    if not logging.root.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    else:
        logging.root.setLevel(level)
    # httpx/httpcore log every request at INFO — hides Kumi's own INFO lines. Opt in with KUMI_HTTP_LOG=1.
    if os.environ.get("KUMI_HTTP_LOG", "").strip().lower() not in ("1", "true", "yes", "debug"):
        for name in ("httpx", "httpcore"):
            logging.getLogger(name).setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the ``kumi`` namespace."""
    return logging.getLogger(name)
