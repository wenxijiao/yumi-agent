"""Yumi user configuration (~/.yumi/config.json) and related paths."""

from yumi.core.features.config.connection import get_saved_connection_code, save_connection_code
from yumi.core.features.config.credentials import (
    _get_provider,
    ensure_chat_model_configured,
    ensure_embedding_provider_not_deepseek,
    ensure_model_ready,
    ensure_provider_available,
    get_api_credentials,
    infer_chat_from_env,
    is_model_available,
)
from yumi.core.features.config.lan import get_lan_secret
from yumi.core.features.config.legacy import ensure_ollama_available, list_local_models, pull_model
from yumi.core.features.config.line import (
    get_line_allowed_user_ids,
    get_line_bot_port,
    get_line_channel_access_token,
    get_line_channel_secret,
    get_line_model_candidates,
    line_incore_enabled,
    line_push_disabled,
    save_line_channel_access_token,
    save_line_channel_secret,
)
from yumi.core.features.config.model import (
    EMBEDDING_CAPABLE_PROVIDERS,
    RECOMMENDED_CHAT_MODEL,
    RECOMMENDED_CHAT_MODELS,
    RECOMMENDED_EMBEDDING_MODEL,
    RECOMMENDED_EMBEDDING_MODELS,
    ModelConfig,
    embeddings_enabled,
)
from yumi.core.features.config.paths import (
    CONFIG_DIR,
    CONFIG_PATH,
    LEGACY_MEMORY_DIR,
    MEMORY_DIR,
    cleanup_memory_data,
    cleanup_user_data,
    ensure_config_dir,
    ensure_memory_dir,
    get_legacy_memory_dir,
    get_memory_dir,
    migrate_legacy_memory_dir,
)
from yumi.core.features.config.setup_wizard import configure_models_noninteractive, run_model_setup
from yumi.core.features.config.store import (
    ensure_full_model_config_file,
    load_model_config,
    load_saved_model_config,
    save_model_config,
)
from yumi.core.features.config.telegram import (
    get_telegram_allowed_user_ids,
    get_telegram_bot_token,
    save_telegram_bot_token,
)

# Re-export for ``from yumi.core.features.config import DEFAULT_SYSTEM_PROMPT``
from yumi.core.features.prompts.defaults import DEFAULT_SYSTEM_PROMPT  # noqa: E402
from yumi.core.features.prompts.store import (
    delete_session_prompt,
    get_session_prompt,
    get_system_prompt,
    reset_system_prompt,
    set_session_prompt,
    set_system_prompt,
)

__all__ = [
    "CONFIG_DIR",
    "CONFIG_PATH",
    "DEFAULT_SYSTEM_PROMPT",
    "LEGACY_MEMORY_DIR",
    "MEMORY_DIR",
    "EMBEDDING_CAPABLE_PROVIDERS",
    "RECOMMENDED_CHAT_MODEL",
    "RECOMMENDED_CHAT_MODELS",
    "RECOMMENDED_EMBEDDING_MODEL",
    "RECOMMENDED_EMBEDDING_MODELS",
    "ModelConfig",
    "embeddings_enabled",
    "cleanup_memory_data",
    "cleanup_user_data",
    "delete_session_prompt",
    "ensure_chat_model_configured",
    "ensure_config_dir",
    "ensure_embedding_provider_not_deepseek",
    "ensure_full_model_config_file",
    "ensure_memory_dir",
    "ensure_model_ready",
    "ensure_ollama_available",
    "ensure_provider_available",
    "infer_chat_from_env",
    "_get_provider",
    "get_api_credentials",
    "get_legacy_memory_dir",
    "get_memory_dir",
    "get_saved_connection_code",
    "get_session_prompt",
    "get_system_prompt",
    "get_lan_secret",
    "get_line_allowed_user_ids",
    "get_line_bot_port",
    "get_line_channel_access_token",
    "get_line_channel_secret",
    "get_line_model_candidates",
    "line_incore_enabled",
    "line_push_disabled",
    "save_line_channel_access_token",
    "save_line_channel_secret",
    "get_telegram_allowed_user_ids",
    "get_telegram_bot_token",
    "is_model_available",
    "list_local_models",
    "load_model_config",
    "load_saved_model_config",
    "migrate_legacy_memory_dir",
    "pull_model",
    "reset_system_prompt",
    "configure_models_noninteractive",
    "run_model_setup",
    "save_connection_code",
    "save_model_config",
    "save_telegram_bot_token",
    "set_session_prompt",
    "set_system_prompt",
]
