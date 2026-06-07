"""Default memory-store construction for the OSS single-user deployment.

This is the one place that constructs the concrete :class:`Memory` and caches
it on the active runtime, keeping that feature dependency out of ``platform``.
"""

from kumi.core.features.memory.memory import Memory
from kumi.core.platform.runtime.accessors import get_runtime


def get_memory_store() -> Memory:
    runtime = get_runtime()
    if runtime.memory_store is None:
        runtime.memory_store = Memory(session_id="default")
    return runtime.memory_store


def get_memory_store_for_identity(identity) -> Memory:
    """Return the Memory store for *identity* via the plugin layer."""
    from kumi.core.platform.plugins import get_memory_factory

    return get_memory_factory().get_for_identity(identity)
