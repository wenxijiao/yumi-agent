"""Deprecated shim — moved to kumi.core.platform.tools.tool_call_normalize.

Re-exports the relocated module so existing ``kumi.core.tool_call_normalize`` imports keep
working. Kept for one release; remove after consumers (incl. L2/L3) migrate.
"""
import sys as _sys

from kumi.core.platform.tools import tool_call_normalize as _moved

_sys.modules[__name__] = _moved
