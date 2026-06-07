"""Telegram bot token and allowlist (config + env)."""

import os

from yumi.core.features.config.store import load_saved_model_config, save_model_config


def get_telegram_bot_token() -> str | None:
    """Return Telegram bot token from env TELEGRAM_BOT_TOKEN or config (env wins)."""
    raw = os.getenv("TELEGRAM_BOT_TOKEN")
    if raw and raw.strip():
        return raw.strip()
    return load_saved_model_config().telegram_bot_token


def get_telegram_allowed_user_ids() -> list[int]:
    """If non-empty, only these Telegram user IDs may use the bot."""
    raw = os.getenv("TELEGRAM_ALLOWED_USER_IDS")
    if raw and raw.strip():
        ids: list[int] = []
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                ids.append(int(part))
            except ValueError:
                pass
        return ids
    return load_saved_model_config().telegram_allowed_user_ids or []


def save_telegram_bot_token(token: str) -> None:
    """Persist Telegram bot token to ~/.yumi/config.json (env TELEGRAM_BOT_TOKEN still overrides at runtime)."""
    normalized = token.strip()
    if not normalized:
        raise ValueError("Telegram bot token cannot be empty.")
    config = load_saved_model_config()
    config.telegram_bot_token = normalized
    save_model_config(config)
