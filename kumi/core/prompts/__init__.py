"""Prompt defaults (``defaults``), persistence (``store``), composition (``composer``).

Import submodules directly (e.g. ``from kumi.core.prompts.store import ...``) to avoid import cycles
with ``kumi.core.config``; this ``__init__`` stays minimal.
"""


def __getattr__(name: str):
    """Lazy re-exports for ``compose_messages`` / ``messages_have_multimodal_images``."""
    if name in ("compose_messages", "messages_have_multimodal_images"):
        from kumi.core.prompts import composer as _composer

        return getattr(_composer, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
