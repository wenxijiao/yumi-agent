"""Deprecated shim — moved to kumi.core.platform.tools.tool.

Re-exports the relocated module so existing ``kumi.core.tool`` imports keep
working. Kept for one release; remove after consumers (incl. L2/L3) migrate.
"""
import sys as _sys

from kumi.core.platform.tools import tool as _moved

_sys.modules[__name__] = _moved
