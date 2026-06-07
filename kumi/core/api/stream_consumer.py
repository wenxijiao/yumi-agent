"""Deprecated shim — moved to kumi.core.platform.http.stream_consumer. Removed in phase E."""
import sys as _sys
from importlib import import_module as _imp

_sys.modules[__name__] = _imp("kumi.core.platform.http.stream_consumer")
