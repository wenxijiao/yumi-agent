"""Persist Kumi Bearer tokens per Telegram user after ``/link`` (local bridge process)."""

from __future__ import annotations

import json
from pathlib import Path

from kumi.core.config.paths import CONFIG_DIR, ensure_config_dir

_BRIDGE_FILE = "telegram_bridge.json"


def _path() -> Path:
    ensure_config_dir()
    return CONFIG_DIR / _BRIDGE_FILE


def load_bridge_map() -> dict[str, str]:
    p = _path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in data.items():
        if isinstance(k, str) and isinstance(v, str) and v.strip():
            out[k] = v.strip()
    return out


def save_token_for_telegram_user(telegram_user_id: int, access_token: str) -> None:
    m = load_bridge_map()
    m[str(int(telegram_user_id))] = access_token.strip()
    p = _path()
    p.write_text(json.dumps(m, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        p.chmod(0o600)
    except OSError:
        pass


def token_for_telegram_user(telegram_user_id: int) -> str | None:
    return load_bridge_map().get(str(int(telegram_user_id)))


def chat_connection_config(telegram_user_id: int | None):
    """Like ``resolve_connection_config("chat")`` but attach Kumi user token when linked."""
    import os

    from kumi.core.platform.security.connection import (
        DEFAULT_LOCAL_SERVER_URL,
        ConnectionConfig,
        resolve_connection_config,
    )

    base = resolve_connection_config("chat")
    if telegram_user_id is None:
        return base
    tok = token_for_telegram_user(telegram_user_id)
    if not tok:
        tok = os.getenv("KUMI_USER_ACCESS_TOKEN", "").strip() or None
    if not tok:
        return base
    if base.mode == "relay":
        return ConnectionConfig(mode="relay", scope="chat", base_url=base.base_url, access_token=tok)
    return ConnectionConfig(
        mode="direct",
        scope="chat",
        base_url=os.getenv("KUMI_SERVER_URL", DEFAULT_LOCAL_SERVER_URL).rstrip("/"),
        access_token=tok,
    )
