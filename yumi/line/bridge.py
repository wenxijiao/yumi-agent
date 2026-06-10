"""Per-LINE-user connection helpers (OSS: stateless, single-user)."""

from __future__ import annotations

from yumi.core.platform.security.connection import ConnectionConfig, resolve_connection_config


def chat_connection_config(line_user_id: str | None) -> ConnectionConfig:
    """Return the chat ConnectionConfig used by the LINE bridge.

    OSS always returns the direct local server config.
    """
    _ = line_user_id
    return resolve_connection_config("chat")
