"""Per-LINE-user connection helpers (OSS: stateless, single-user).

Persistent token mapping (enterprise ``/link`` flow) lives in the
``kumi_enterprise.line`` package.
"""

from __future__ import annotations

import os

from kumi.core.platform.security.connection import (
    DEFAULT_LOCAL_SERVER_URL,
    ConnectionConfig,
    resolve_connection_config,
)


def chat_connection_config(line_user_id: str | None) -> ConnectionConfig:
    """Return the chat ConnectionConfig used by the LINE bridge.

    OSS always returns the direct local server config — there is no
    multi-tenant token mapping to consult.
    """
    base = resolve_connection_config("chat")
    tok = os.getenv("KUMI_USER_ACCESS_TOKEN", "").strip() or None
    if not tok:
        return base
    return ConnectionConfig(
        mode="direct",
        scope="chat",
        base_url=os.getenv("KUMI_SERVER_URL", DEFAULT_LOCAL_SERVER_URL).rstrip("/"),
        access_token=tok,
    )
