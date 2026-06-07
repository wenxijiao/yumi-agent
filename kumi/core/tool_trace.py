"""Deprecated shim — moved to kumi.core.platform.tools.tool_trace.

Re-exports the relocated module so existing ``kumi.core.tool_trace`` imports keep
working. Kept for one release; remove after consumers (incl. L2/L3) migrate.
"""
import sys as _sys

from kumi.core.platform.tools import tool_trace as _moved

_sys.modules[__name__] = _moved
