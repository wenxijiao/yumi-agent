"""Deprecated shim — moved to kumi.core.platform.security.http_config.

Re-exports the relocated module so existing ``kumi.core.http_config`` imports keep
working. Kept for one release; remove after consumers (incl. L2/L3) migrate.
"""
import sys as _sys

from kumi.core.platform.security import http_config as _moved

_sys.modules[__name__] = _moved
