"""Deprecated shim — moved to kumi.core.platform.env_load.

Re-exports the relocated module so existing ``kumi.core.env_load`` imports keep
working. Kept for one release; remove after consumers (incl. L2/L3) migrate.
"""
import sys as _sys

from kumi.core.platform import env_load as _moved

_sys.modules[__name__] = _moved
