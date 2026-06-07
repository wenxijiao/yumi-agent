"""Relay / pairing connection code persistence."""

from kumi.core.features.config.store import load_saved_model_config, save_model_config


def get_saved_connection_code() -> str | None:
    """Return the persisted connection code from ~/.kumi/config.json."""
    return load_saved_model_config().connection_code


def save_connection_code(code: str) -> None:
    """Persist a connection code to ~/.kumi/config.json."""
    config = load_saved_model_config()
    config.connection_code = code
    save_model_config(config)
