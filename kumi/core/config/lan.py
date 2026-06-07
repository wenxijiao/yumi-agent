"""LAN signing secret."""

import secrets

from kumi.core.config.store import load_saved_model_config, save_model_config


def get_lan_secret() -> str:
    """Return the server's LAN signing secret, auto-generating on first use."""
    config = load_saved_model_config()
    if config.lan_secret:
        return config.lan_secret
    config.lan_secret = secrets.token_urlsafe(32)
    save_model_config(config)
    return config.lan_secret
