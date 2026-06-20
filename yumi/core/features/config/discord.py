"""Discord bot token and allowlist (config + env)."""

import os

from yumi.core.features.config.store import load_saved_model_config, save_model_config


def get_discord_bot_token() -> str | None:
    """Return Discord bot token from env DISCORD_BOT_TOKEN or config (env wins)."""
    raw = os.getenv("DISCORD_BOT_TOKEN")
    if raw and raw.strip():
        return raw.strip()
    return load_saved_model_config().discord_bot_token


def get_discord_allowed_user_ids() -> list[int]:
    """If non-empty, only these Discord user IDs may use the bot."""
    raw = os.getenv("DISCORD_ALLOWED_USER_IDS")
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
    return load_saved_model_config().discord_allowed_user_ids or []


def save_discord_bot_token(token: str) -> None:
    """Persist Discord bot token to ~/.yumi/config.json (env DISCORD_BOT_TOKEN still overrides at runtime)."""
    normalized = token.strip()
    if not normalized:
        raise ValueError("Discord bot token cannot be empty.")
    config = load_saved_model_config()
    config.discord_bot_token = normalized
    save_model_config(config)
