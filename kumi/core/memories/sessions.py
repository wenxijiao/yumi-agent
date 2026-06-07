"""Session metadata normalization helpers."""

from __future__ import annotations

from kumi.core.memories.constants import ACTIVE_SESSION_STATUS, DEFAULT_SESSION_TITLE, DELETED_SESSION_STATUS


def normalize_session_status(status: str) -> str:
    normalized = str(status or ACTIVE_SESSION_STATUS).strip().lower()
    if normalized not in {ACTIVE_SESSION_STATUS, DELETED_SESSION_STATUS}:
        raise ValueError("Session status must be one of: active, deleted.")
    return normalized


def normalize_session_title(title: str | None) -> str:
    if title is None:
        return DEFAULT_SESSION_TITLE
    normalized = " ".join(title.strip().split())
    return normalized[:80] if normalized else DEFAULT_SESSION_TITLE


def derive_session_title(content: str) -> str:
    normalized = " ".join(content.strip().split())
    if not normalized:
        return DEFAULT_SESSION_TITLE
    return normalized[:60]
