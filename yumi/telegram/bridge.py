"""Per-Telegram-user connection helpers (OSS: stateless, single-user)."""

from __future__ import annotations

from yumi.core.platform.plugins import get_bridge_scope
from yumi.core.platform.security.connection import ConnectionConfig


def chat_connection_config(telegram_user_id: int | None) -> ConnectionConfig:
    """Return the chat connection for this Telegram user.

    Resolved through the ``BridgeScope`` plugin port: the single-user default
    returns the shared connection; a multi-user plugin maps the user to their
    own account/connection.
    """
    return get_bridge_scope().connection("telegram", "" if telegram_user_id is None else str(telegram_user_id))
