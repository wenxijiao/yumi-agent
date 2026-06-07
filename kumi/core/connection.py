"""Deprecated shim — moved to kumi.core.platform.security.connection.

Re-exports the relocated module so existing ``kumi.core.connection`` imports keep
working. Kept for one release; remove after consumers (incl. L2/L3) migrate.
"""
import sys as _sys

from kumi.core.platform.security import connection as _moved

_sys.modules[__name__] = _moved
