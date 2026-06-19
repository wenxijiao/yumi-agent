"""Per-Discord-user connection helpers (OSS: stateless, single-user)."""

from __future__ import annotations

from yumi.core.platform.security.connection import ConnectionConfig, resolve_connection_config


def chat_connection_config(discord_user_id: int | None) -> ConnectionConfig:  # noqa: ARG001
    """Return the chat connection used by the Discord bridge."""
    return resolve_connection_config("chat")
