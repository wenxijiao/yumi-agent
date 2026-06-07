"""Deprecated shim package — moved to kumi.core.features.prompts.

Aliases the relocated package so top-level ``from kumi.core.prompts import X`` keeps
working. Submodule imports should use the new path. Removed in phase E.
"""
import sys as _sys
from importlib import import_module as _imp

_sys.modules[__name__] = _imp("kumi.core.features.prompts")
