"""LINE Messaging API credentials and flags (config + env)."""

from __future__ import annotations

import os

from kumi.core.features.config.store import load_saved_model_config, save_model_config


def get_line_channel_secret() -> str | None:
    raw = os.getenv("LINE_CHANNEL_SECRET")
    if raw and raw.strip():
        return raw.strip()
    v = load_saved_model_config().line_channel_secret
    return v.strip() if v else None


def get_line_channel_access_token() -> str | None:
    raw = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    if raw and raw.strip():
        return raw.strip()
    v = load_saved_model_config().line_channel_access_token
    return v.strip() if v else None


def line_push_disabled() -> bool:
    return os.getenv("LINE_DISABLE_PUSH", "").strip().lower() in ("1", "true", "yes")


def line_incore_enabled() -> bool:
    return os.getenv("KUMI_LINE_INCORE", "").strip().lower() in ("1", "true", "yes")


def get_line_bot_port() -> int:
    raw = os.getenv("LINE_BOT_PORT")
    if raw and raw.strip():
        try:
            p = int(raw.strip())
            return max(1, min(65535, p))
        except ValueError:
            pass
    return int(load_saved_model_config().line_bot_port or 8788)


def get_line_allowed_user_ids() -> list[str]:
    raw = os.getenv("LINE_ALLOWED_USER_IDS")
    if raw and raw.strip():
        return [p.strip() for p in raw.split(",") if p.strip()]
    return list(load_saved_model_config().line_allowed_user_ids or [])


def get_line_model_candidates() -> list[str]:
    raw = os.getenv("KUMI_LINE_MODEL_CANDIDATES")
    if raw and raw.strip():
        return [p.strip() for p in raw.split(",") if p.strip()][:20]
    return ["gpt-4o-mini", "gpt-4o", "gemini-2.0-flash", "qwen3.5:9b"]


def save_line_channel_secret(secret: str) -> None:
    s = secret.strip()
    if not s:
        raise ValueError("LINE channel secret cannot be empty.")
    cfg = load_saved_model_config()
    cfg.line_channel_secret = s
    save_model_config(cfg)


def save_line_channel_access_token(token: str) -> None:
    t = token.strip()
    if not t:
        raise ValueError("LINE channel access token cannot be empty.")
    cfg = load_saved_model_config()
    cfg.line_channel_access_token = t
    save_model_config(cfg)
