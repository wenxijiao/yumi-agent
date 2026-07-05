"""Request-scoped identity for Yumi core.

Single-user OSS default: every request is the synthetic local user.

Plugins can replace :func:`get_current_identity` semantics by registering their
own :class:`~yumi.core.platform.plugins.ports.IdentityProvider`, but the
dataclass itself is shared so core code can pass identities through without
depending on a higher layer.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Literal

SINGLE_USER_ID = "_local"


@dataclass(frozen=True, slots=True)
class Identity:
    """Authenticated principal (or the synthetic local user in single-user mode)."""

    user_id: str
    scopes: tuple[str, ...] = ("*",)
    source: Literal["single_user", "plugin", "internal"] = "single_user"


LOCAL_IDENTITY: Identity = Identity(
    user_id=SINGLE_USER_ID,
    scopes=("*",),
    source="single_user",
)


_identity_ctx: ContextVar[Identity | None] = ContextVar("yumi_identity", default=None)


def set_current_identity(identity: Identity | None) -> Any:
    """Bind *identity* for the current async context. Returns a reset token."""
    return _identity_ctx.set(identity)


def reset_current_identity(token: Any) -> None:
    _identity_ctx.reset(token)


def context_identity() -> Identity | None:
    """Return the identity bound on the current async context, or ``None``."""
    return _identity_ctx.get()


def has_admin_scope(identity: Identity) -> bool:
    """True if *identity* may access admin-only routes."""
    return "*" in identity.scopes or "admin" in identity.scopes


def effective_caller_user_id(fallback_user_id: str | None = None) -> str | None:
    """The user on whose behalf the current work runs.

    Prefers the authenticated principal bound to the async context (via the
    active ``IdentityProvider``); an ``internal`` system identity defers to
    *fallback_user_id* (e.g. the chat session owner, so proactive/timer turns
    act for the user they belong to). In single-user mode this is simply the
    synthetic local user; plugins may bind richer identities.

    Edge dispatch stamps this onto every ``tool_call`` frame as
    ``caller_user_id`` so a shared edge can scope its work to the caller.
    It is derived server-side only — never from model output.
    """
    ident: Identity | None
    try:
        # Lazy import: the plugin registry depends on this module.
        from yumi.core.platform.plugins import get_identity_provider

        ident = get_identity_provider().current()
    except Exception:
        ident = context_identity()
    uid = (getattr(ident, "user_id", None) or "").strip() or None
    if uid and getattr(ident, "source", None) != "internal":
        return uid
    return fallback_user_id or uid
