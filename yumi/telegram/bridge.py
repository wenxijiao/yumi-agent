"""Per-Telegram-user connection helpers for the local single-user server."""

from __future__ import annotations

from yumi.core.platform.plugins import get_bridge_scope
from yumi.core.platform.security.connection import ConnectionConfig


def chat_connection_config(telegram_user_id: int | None) -> ConnectionConfig:
    """Return the chat connection for this Telegram user.

    Resolved through the ``BridgeScope`` plugin port: the single-user default
    returns the shared connection; an identity plugin may map the user to their
    own account or connection.
    """
    return get_bridge_scope().connection("telegram", "" if telegram_user_id is None else str(telegram_user_id))
