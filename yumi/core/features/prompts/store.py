"""Persisted system / per-session prompts (backed by ~/.yumi/config.json via ModelConfig).

The model-facing prompt is a **stack of layers**, not a single overwritable
string::

    DEFAULT_SYSTEM_PROMPT          ← L1 OSS (identity, language, tone, honesty)
    + plugin extension sections    ← L2 tenant / L3 brand / app-aware blocks
    + user addendum                ← what the user wrote via /system set

Each layer adds to the next. The user can only edit the addendum (their own
"on top of the default" instructions) — they can't clobber the base prompt
or plugin context. Session-scoped addendum overrides the global addendum
when both are set; clearing it falls back to the global one.
"""

from yumi.core.features.prompts.defaults import DEFAULT_SYSTEM_PROMPT

# Note: ``yumi.core.features.config`` re-exports several of the functions below, so
# importing it at module top would form a cycle. Functions that need the
# config store import it lazily.


def _global_addendum() -> str:
    """The user's global ``/system set`` text — appended to defaults, not replacing them."""
    from yumi.core.features.config.store import load_model_config

    config = load_model_config()
    return (config.system_prompt or "").strip()


def set_system_prompt(system_prompt: str) -> str:
    """Save the user's global addendum. Appended to defaults; does NOT replace them."""
    from yumi.core.features.config.store import load_saved_model_config, save_model_config

    normalized = system_prompt.strip()
    if not normalized:
        raise ValueError("System prompt cannot be empty.")

    config = load_saved_model_config()
    config.system_prompt = normalized
    save_model_config(config)
    return normalized


def reset_system_prompt() -> str:
    """Clear the user's global addendum and return what the prompt now is without it."""
    from yumi.core.features.config.store import load_saved_model_config, save_model_config

    config = load_saved_model_config()
    config.system_prompt = None
    save_model_config(config)
    return _compose_layers(session_addendum=None)


def get_session_prompt(session_id: str) -> str | None:
    """Return a per-session addendum, or None when only the global one (or defaults) applies."""
    from yumi.core.features.config.store import load_saved_model_config

    return load_saved_model_config().session_prompts.get(session_id)


def set_session_prompt(session_id: str, prompt: str) -> str:
    """Save a per-session addendum. Wins over the global addendum when both are set."""
    from yumi.core.features.config.store import load_saved_model_config, save_model_config

    config = load_saved_model_config()
    config.session_prompts[session_id] = prompt.strip()
    save_model_config(config)
    return config.session_prompts[session_id]


def delete_session_prompt(session_id: str) -> None:
    from yumi.core.features.config.store import load_saved_model_config, save_model_config

    config = load_saved_model_config()
    config.session_prompts.pop(session_id, None)
    save_model_config(config)


def _plugin_sections() -> list[str]:
    """Identity-aware contextual blocks supplied by the active plugin (L2/L3).

    Imports the plugin registry lazily because :mod:`yumi.core.features.config`
    eagerly pulls in this module during its own initialization, and the
    plugin layer in turn depends on config — a top-level import here
    would form a cycle.
    """
    try:
        from yumi.core.platform.plugins import get_current_identity, get_system_prompt_extender
    except ImportError:
        return []
    try:
        identity = get_current_identity()
    except Exception:
        return []
    try:
        sections = get_system_prompt_extender().extra_system_prompt_sections(identity)
    except Exception:
        return []
    return [s.strip() for s in (sections or []) if isinstance(s, str) and s.strip()]


def _compose_layers(*, session_addendum: str | None) -> str:
    parts: list[str] = [DEFAULT_SYSTEM_PROMPT.strip()]
    parts.extend(_plugin_sections())
    addendum = (session_addendum or "").strip() or _global_addendum()
    if addendum:
        parts.append(addendum)
    return "\n\n".join(parts)


def get_system_prompt() -> str:
    """Return the composed global prompt (default + plugin sections + global addendum).

    No session override is applied. Use :func:`get_effective_system_prompt`
    for the per-session view.
    """
    return _compose_layers(session_addendum=None)


def get_effective_system_prompt(session_id: str) -> str:
    """Composed system prompt for a session: defaults + plugin sections + addendum."""
    return _compose_layers(session_addendum=get_session_prompt(session_id))
