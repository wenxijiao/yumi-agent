"""Deprecated shim — moved to kumi.core.platform.exceptions.

Re-exports the relocated module so existing ``kumi.core.exceptions`` imports keep
working. Kept for one release; remove after consumers (incl. L2/L3) migrate.
"""
import sys as _sys

from kumi.core.platform import exceptions as _moved

_sys.modules[__name__] = _moved
