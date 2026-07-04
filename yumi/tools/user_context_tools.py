"""Built-in tools for user-controlled stable context."""

from __future__ import annotations

from yumi.core.features.chat.context import get_chat_owner_user_id
from yumi.core.features.memory.models import LONG_TERM_MEMORY_KINDS
from yumi.core.platform.plugins import get_memory_factory

_STABLE_USER_CONTEXT_SESSION = "__stable_user_context__"
_DISALLOWED_KINDS = {"tool_observation"}
_DEFAULT_KIND = "fact"


def _memory_store():
    return get_memory_factory().get_for_session_owner(get_chat_owner_user_id())


def _normalize_kind(kind: str | None) -> str:
    normalized = str(kind or _DEFAULT_KIND).strip().lower().replace(" ", "_")
    if normalized not in LONG_TERM_MEMORY_KINDS or normalized in _DISALLOWED_KINDS:
        allowed = ", ".join(sorted(k for k in LONG_TERM_MEMORY_KINDS if k not in _DISALLOWED_KINDS))
        raise ValueError(f"kind must be one of: {allowed}.")
    return normalized


def remember_user_context(content: str, kind: str = _DEFAULT_KIND, importance: float = 0.85) -> str:
    """Save a durable user context memory.

    Use this only when the user explicitly asks Yumi to remember something, or
    when the user directly confirms that a suggested memory should be saved.
    Do not save secrets, passwords, payment details, or sensitive personal data
    unless the user clearly asks for that exact information to be remembered.
    """
    normalized_content = " ".join(str(content or "").split())
    if not normalized_content:
        raise ValueError("content cannot be empty.")
    normalized_kind = _normalize_kind(kind)
    score = max(0.0, min(1.0, float(importance)))
    row = _memory_store().create_long_term_memory(
        kind=normalized_kind,
        content=normalized_content,
        session_id=_STABLE_USER_CONTEXT_SESSION,
        confidence=0.95,
        importance=score,
    )
    return f"Remembered {row['kind']} memory {row['id']}: {row['content']}"


def list_user_context(kind: str = "", limit: int = 20) -> str:
    """List durable stable user context memories Yumi currently has saved."""
    normalized_kind = _normalize_kind(kind) if str(kind or "").strip() else None
    capped = max(1, min(50, int(limit)))
    rows = _memory_store().list_long_term_memories(kind=normalized_kind, session_id=None, limit=capped)
    rows = [row for row in rows if row.get("kind") not in _DISALLOWED_KINDS]
    if not rows:
        return "No stable user context memories are saved."
    lines = ["Stable user context memories:"]
    for row in rows:
        lines.append(f"- {row['id']} [{row['kind']}] {row['content']}")
    return "\n".join(lines)


def forget_user_context(memory_id: str) -> str:
    """Delete a durable user context memory by id.

    Use after the user asks Yumi to forget a saved memory. If the user names a
    memory but not its id, call list_user_context first to find the matching id.
    """
    normalized_id = str(memory_id or "").strip()
    if not normalized_id:
        raise ValueError("memory_id cannot be empty.")
    deleted = _memory_store().delete_long_term_memory(normalized_id)
    if not deleted:
        return f"No stable user context memory found for id {normalized_id}."
    return f"Forgot stable user context memory {normalized_id}."
