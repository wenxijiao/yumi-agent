"""Configuration routes.

Read endpoints expose non-secret configuration needed by the local UI and bots.
Write endpoints require admin scope. The single-user default identity is admin
on a trusted local machine (the server binds 127.0.0.1 by default; see
SECURITY.md), while plugins can provide per-user authorization under other
deployment models.
"""

from __future__ import annotations

import yumi.core.platform.runtime.accessors as _state
from fastapi import APIRouter, HTTPException
from yumi.core.features.config import (
    CONFIG_PATH,
    DEFAULT_SYSTEM_PROMPT,
    EMBEDDING_CAPABLE_PROVIDERS,
    delete_session_prompt,
    ensure_config_dir,
    ensure_embedding_provider_supported,
    ensure_model_ready,
    ensure_provider_available,
    get_api_credentials,
    get_session_prompt,
    get_system_prompt,
    load_model_config,
    load_saved_model_config,
    reset_system_prompt,
    save_model_config,
    set_session_prompt,
    set_system_prompt,
)
from yumi.core.platform.exceptions import ProviderNotReadyError
from yumi.core.platform.http.dependencies import CurrentIdentity
from yumi.core.platform.http.http_errors import model_apply_failed_http, provider_not_ready_http, unknown_provider_http
from yumi.core.platform.http.schemas import (
    ModelConfigUpdateRequest,
    SessionPromptRequest,
    SystemPromptUpdateRequest,
    UIPreferencesRequest,
)
from yumi.core.platform.plugins import get_session_scope, has_admin_scope
from yumi.core.platform.providers import SUPPORTED_PROVIDERS, create_provider
from yumi.logging_config import get_logger

router = APIRouter()
logger = get_logger(__name__)

_SUPPORTED_SEARCH_PROVIDERS = ("auto", "tavily", "brave", "serper", "searxng", "duckduckgo")
_SUPPORTED_STT_PROVIDERS = ("disabled", "whisper", "openai", "gemini", "dashscope", "grok")
_SUPPORTED_TTS_PROVIDERS = ("disabled", "system", "dashscope", "qwen", "openai", "gemini", "grok")
_CLOUD_VOICE_PROVIDERS = ("openai", "gemini", "grok")


def _require_admin(identity) -> None:
    if not has_admin_scope(identity):
        raise HTTPException(status_code=403, detail="Admin scope required for server configuration.")


@router.get("/config/system-prompt")
async def get_system_prompt_endpoint(identity: CurrentIdentity):
    system_prompt = get_system_prompt()
    return {
        "system_prompt": system_prompt,
        "is_default": system_prompt == DEFAULT_SYSTEM_PROMPT,
    }


@router.put("/config/system-prompt")
async def update_system_prompt_endpoint(identity: CurrentIdentity, request: SystemPromptUpdateRequest):
    _require_admin(identity)
    try:
        system_prompt = set_system_prompt(request.system_prompt)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "success", "system_prompt": system_prompt}


@router.delete("/config/system-prompt")
async def reset_system_prompt_endpoint(identity: CurrentIdentity):
    _require_admin(identity)
    system_prompt = reset_system_prompt()
    return {"status": "success", "system_prompt": system_prompt, "is_default": True}


def _restore_config_file(backup_before: str | None) -> None:
    if backup_before is None:
        if CONFIG_PATH.exists():
            CONFIG_PATH.unlink()
        return
    ensure_config_dir()
    CONFIG_PATH.write_text(backup_before, encoding="utf-8")


def _model_config_public_dict() -> dict:
    runtime = load_model_config()
    saved = load_saved_model_config()
    creds = get_api_credentials()
    return {
        "chat_provider": runtime.chat_provider,
        "chat_model": runtime.chat_model or "",
        "embedding_provider": runtime.embedding_provider,
        "embedding_model": runtime.embedding_model or "",
        "memory_max_recent_messages": runtime.memory_max_recent_messages,
        "memory_max_related_messages": runtime.memory_max_related_messages,
        "chat_append_current_time": runtime.chat_append_current_time,
        "chat_append_tool_use_instruction": runtime.chat_append_tool_use_instruction,
        "edge_tools_enable_dynamic_routing": runtime.edge_tools_enable_dynamic_routing,
        "edge_tools_retrieval_limit": runtime.edge_tools_retrieval_limit,
        "stt_provider": runtime.stt_provider,
        "stt_backend": runtime.stt_backend,
        "stt_model": runtime.stt_model or "",
        "stt_model_dir": runtime.stt_model_dir or "",
        "stt_language": runtime.stt_language,
        "tts_provider": runtime.tts_provider,
        "tts_voice": runtime.tts_voice or "",
        "tts_model": runtime.tts_model or "",
        "tts_language": runtime.tts_language,
        "tts_api_key_saved": bool(saved.tts_api_key and str(saved.tts_api_key).strip()),
        "openai_api_key_saved": bool(saved.openai_api_key and str(saved.openai_api_key).strip()),
        "gemini_api_key_saved": bool(saved.gemini_api_key and str(saved.gemini_api_key).strip()),
        "claude_api_key_saved": bool(saved.claude_api_key and str(saved.claude_api_key).strip()),
        "openai_api_key_effective": bool(creds.get("openai_api_key")),
        "gemini_api_key_effective": bool(creds.get("gemini_api_key")),
        "claude_api_key_effective": bool(creds.get("claude_api_key")),
        "deepseek_api_key_saved": bool(saved.deepseek_api_key and str(saved.deepseek_api_key).strip()),
        "deepseek_api_key_effective": bool(creds.get("deepseek_api_key")),
        "grok_api_key_saved": bool(saved.grok_api_key and str(saved.grok_api_key).strip()),
        "grok_api_key_effective": bool(creds.get("grok_api_key")),
        "openai_base_url": saved.openai_base_url or "",
        "deepseek_base_url": saved.deepseek_base_url or "",
        "grok_base_url": saved.grok_base_url or "",
        "search_provider": runtime.search_provider,
        "tavily_api_key_saved": bool(saved.tavily_api_key and str(saved.tavily_api_key).strip()),
        "brave_search_api_key_saved": bool(saved.brave_search_api_key and str(saved.brave_search_api_key).strip()),
        "serper_api_key_saved": bool(saved.serper_api_key and str(saved.serper_api_key).strip()),
        "searxng_base_url": saved.searxng_base_url or "",
    }


@router.get("/config/model")
async def get_model_config_endpoint(identity: CurrentIdentity):
    return _model_config_public_dict()


def _refresh_embeddings_and_reindex(config) -> None:
    """Apply an embedding provider/model change without a restart.

    Points the runtime embed provider at the new model, drops the cached memory
    store so it is rebuilt with the new embedding, and (when embeddings are on)
    rebuilds the LanceDB index from SQLite on a daemon thread — re-embedding every
    message with the new model. SQLite (the source of truth) is untouched.
    """
    from yumi.core.features.config import embeddings_enabled
    from yumi.core.features.memory.embedding_state import set_embed_provider
    from yumi.core.features.memory.store import get_memory_store

    runtime = _state.get_runtime()
    try:
        if embeddings_enabled(config):
            if config.embedding_provider == config.chat_provider and runtime.bot:
                embed_provider = runtime.bot.provider
            else:
                embed_provider = create_provider(config.embedding_provider)
            set_embed_provider(embed_provider)
        else:
            set_embed_provider(None)
    except Exception:
        logger.exception("Failed to refresh embedding provider after change")
        return

    # Drop the cached Memory so the next access (and the rebuild) uses the new model.
    runtime.memory_store = None
    if not embeddings_enabled(config):
        # Switched embeddings off — existing vectors go unused (keyword fallback);
        # no re-embed needed.
        return

    def _reindex() -> None:
        try:
            n = get_memory_store().rebuild_index_from_sqlite()
            logger.info(
                "Rebuilt memory index after embedding change (provider=%s, model=%s, %s messages).",
                config.embedding_provider,
                config.embedding_model,
                n,
            )
        except Exception:
            logger.warning("Background memory reindex after embedding change failed", exc_info=True)

    import threading

    threading.Thread(target=_reindex, daemon=True, name="yumi-embed-reindex").start()


@router.put("/config/model")
async def update_model_config_endpoint(request: ModelConfigUpdateRequest, identity: CurrentIdentity = None):
    if identity is not None:
        _require_admin(identity)
    if request.chat_provider and request.chat_provider not in SUPPORTED_PROVIDERS:
        raise unknown_provider_http(role="chat", name=request.chat_provider, supported=SUPPORTED_PROVIDERS)
    if request.embedding_provider and request.embedding_provider not in (*EMBEDDING_CAPABLE_PROVIDERS, "disabled"):
        # Only ollama/openai/gemini can embed; claude/deepseek would pass a bare
        # provider check but their embed() raises. Validate against the real set.
        raise unknown_provider_http(
            role="embedding", name=request.embedding_provider, supported=EMBEDDING_CAPABLE_PROVIDERS
        )
    current = load_saved_model_config()
    prev_embedding_provider = current.embedding_provider
    prev_embedding_model = current.embedding_model
    target_stt_provider = (request.stt_provider or current.stt_provider or "disabled").strip().lower()
    if request.stt_provider and request.stt_provider not in _SUPPORTED_STT_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported STT provider. Use one of: {', '.join(_SUPPORTED_STT_PROVIDERS)}.",
        )
    if request.stt_backend and target_stt_provider == "whisper" and request.stt_backend != "faster-whisper":
        raise HTTPException(status_code=400, detail="Unsupported Whisper STT backend. Use 'faster-whisper'.")
    if request.stt_model:
        from yumi.core.features.stt import WHISPER_MULTILINGUAL_MODELS

        if target_stt_provider == "whisper" and request.stt_model not in WHISPER_MULTILINGUAL_MODELS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported Whisper model. Use one of: {', '.join(WHISPER_MULTILINGUAL_MODELS)}.",
            )
    if request.tts_provider and request.tts_provider not in _SUPPORTED_TTS_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported TTS provider. Use one of: {', '.join(_SUPPORTED_TTS_PROVIDERS)}.",
        )
    if request.search_provider and request.search_provider.strip().lower() not in _SUPPORTED_SEARCH_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported search provider. Use one of: {', '.join(_SUPPORTED_SEARCH_PROVIDERS)}.",
        )

    backup_before = CONFIG_PATH.read_text(encoding="utf-8") if CONFIG_PATH.exists() else None

    config = current
    provider_changed = False
    keys_or_base_changed = False

    if request.chat_provider and request.chat_provider != config.chat_provider:
        config.chat_provider = request.chat_provider
        provider_changed = True
    if request.chat_model:
        config.chat_model = request.chat_model
    if request.embedding_provider:
        config.embedding_provider = request.embedding_provider
    if request.embedding_model:
        config.embedding_model = request.embedding_model
    if request.memory_max_recent_messages is not None:
        config.memory_max_recent_messages = request.memory_max_recent_messages
    if request.memory_max_related_messages is not None:
        config.memory_max_related_messages = request.memory_max_related_messages
    if request.chat_append_current_time is not None:
        config.chat_append_current_time = request.chat_append_current_time
    if request.chat_append_tool_use_instruction is not None:
        config.chat_append_tool_use_instruction = request.chat_append_tool_use_instruction
    if request.edge_tools_enable_dynamic_routing is not None:
        config.edge_tools_enable_dynamic_routing = request.edge_tools_enable_dynamic_routing
    if request.edge_tools_retrieval_limit is not None:
        config.edge_tools_retrieval_limit = request.edge_tools_retrieval_limit
    if request.stt_provider is not None:
        config.stt_provider = request.stt_provider.strip() or "disabled"
    if request.stt_backend is not None:
        config.stt_backend = request.stt_backend.strip() or "faster-whisper"
    if request.stt_model is not None:
        v = request.stt_model.strip()
        config.stt_model = v if v else None
    if request.stt_model_dir is not None:
        v = request.stt_model_dir.strip()
        config.stt_model_dir = v if v else None
    if request.stt_language is not None:
        config.stt_language = request.stt_language.strip() or "auto"
    if request.tts_provider is not None:
        config.tts_provider = request.tts_provider.strip() or "disabled"
    if request.tts_voice is not None:
        v = request.tts_voice.strip()
        config.tts_voice = v if v else None
    if request.tts_model is not None:
        v = request.tts_model.strip()
        config.tts_model = v if v else None
    if request.tts_api_key is not None and request.tts_api_key.strip():
        config.tts_api_key = request.tts_api_key.strip()
    if request.tts_language is not None:
        config.tts_language = request.tts_language.strip() or "auto"
    if request.openai_api_key is not None and request.openai_api_key.strip():
        config.openai_api_key = request.openai_api_key.strip()
        keys_or_base_changed = True
    if request.gemini_api_key is not None and request.gemini_api_key.strip():
        config.gemini_api_key = request.gemini_api_key.strip()
        keys_or_base_changed = True
    if request.claude_api_key is not None and request.claude_api_key.strip():
        config.claude_api_key = request.claude_api_key.strip()
        keys_or_base_changed = True
    if request.openai_base_url is not None:
        v = request.openai_base_url.strip()
        config.openai_base_url = v if v else None
        keys_or_base_changed = True
    if request.deepseek_api_key is not None and request.deepseek_api_key.strip():
        config.deepseek_api_key = request.deepseek_api_key.strip()
        keys_or_base_changed = True
    if request.deepseek_base_url is not None:
        v = request.deepseek_base_url.strip()
        config.deepseek_base_url = v if v else None
        keys_or_base_changed = True
    if request.grok_api_key is not None and request.grok_api_key.strip():
        config.grok_api_key = request.grok_api_key.strip()
        keys_or_base_changed = True
    if request.grok_base_url is not None:
        v = request.grok_base_url.strip()
        config.grok_base_url = v if v else None
        keys_or_base_changed = True
    if request.search_provider is not None and request.search_provider.strip():
        config.search_provider = request.search_provider.strip().lower()
    if request.tavily_api_key is not None and request.tavily_api_key.strip():
        config.tavily_api_key = request.tavily_api_key.strip()
    if request.brave_search_api_key is not None and request.brave_search_api_key.strip():
        config.brave_search_api_key = request.brave_search_api_key.strip()
    if request.serper_api_key is not None and request.serper_api_key.strip():
        config.serper_api_key = request.serper_api_key.strip()
    if request.searxng_base_url is not None:
        v = request.searxng_base_url.strip()
        config.searxng_base_url = v if v else None

    try:
        ensure_embedding_provider_supported(config.embedding_provider)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        save_model_config(config)
        seen: set[str] = set()
        providers_to_check = [config.chat_provider, config.embedding_provider]
        if config.stt_provider in ("openai", "gemini", "grok"):
            providers_to_check.append(config.stt_provider)
        if config.tts_provider in _CLOUD_VOICE_PROVIDERS:
            providers_to_check.append(config.tts_provider)
        for prov in providers_to_check:
            if prov == "disabled":
                continue
            if prov in seen:
                continue
            seen.add(prov)
            ensure_provider_available(prov)
        if config.embedding_provider == "fastembed" and config.embedding_model:
            ensure_model_ready("fastembed", config.embedding_model)
    except ProviderNotReadyError as exc:
        _restore_config_file(backup_before)
        raise provider_not_ready_http(exc) from exc

    need_reinit = provider_changed or (
        keys_or_base_changed and config.chat_provider in ("openai", "gemini", "claude", "deepseek", "grok")
    )

    if _state.get_runtime().bot:
        try:
            if need_reinit:
                await _state.get_runtime().bot.provider.shutdown(_state.get_runtime().bot.model_name)
                _state.get_runtime().bot.provider = create_provider(config.chat_provider)
                _state.get_runtime().bot.model_name = config.chat_model
                await _state.get_runtime().bot.warm_up()
            elif request.chat_model:
                await _state.get_runtime().bot.change_model(config.chat_model)
        except Exception as exc:
            logger.exception("Failed to apply model change after PUT /config/model")
            raise model_apply_failed_http(phase="reload_provider_or_model", exc=exc) from exc

    if config.embedding_provider != prev_embedding_provider or config.embedding_model != prev_embedding_model:
        _refresh_embeddings_and_reindex(config)

    return {"status": "success", **_model_config_public_dict()}


@router.get("/config/session-prompt/{session_id}")
async def get_session_prompt_endpoint(identity: CurrentIdentity, session_id: str):
    sid = get_session_scope().qualify_session_http(identity, session_id)
    prompt = get_session_prompt(sid)
    return {
        "session_id": sid,
        "system_prompt": prompt,
        "is_custom": prompt is not None,
    }


@router.put("/config/session-prompt/{session_id}")
async def update_session_prompt_endpoint(identity: CurrentIdentity, session_id: str, request: SessionPromptRequest):
    sid = get_session_scope().qualify_session_http(identity, session_id)
    prompt = set_session_prompt(sid, request.system_prompt)
    return {"status": "success", "session_id": sid, "system_prompt": prompt}


@router.delete("/config/session-prompt/{session_id}")
async def delete_session_prompt_endpoint(identity: CurrentIdentity, session_id: str):
    sid = get_session_scope().qualify_session_http(identity, session_id)
    delete_session_prompt(sid)
    return {"status": "success", "session_id": sid}


@router.get("/config/ui")
async def get_ui_preferences_endpoint(identity: CurrentIdentity):
    config = load_saved_model_config()
    return {"dark_mode": config.ui_dark_mode}


@router.put("/config/ui")
async def update_ui_preferences_endpoint(identity: CurrentIdentity, request: UIPreferencesRequest):
    _require_admin(identity)
    config = load_saved_model_config()
    config.ui_dark_mode = request.dark_mode
    save_model_config(config)
    return {"status": "success", "dark_mode": config.ui_dark_mode}
