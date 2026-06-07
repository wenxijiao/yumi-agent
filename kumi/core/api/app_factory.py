"""FastAPI assembly for the Kumi core API.

This module owns process lifecycle and HTTP composition only. Every resource
endpoint lives in ``kumi.core.api.routers``; this file does not declare any
route, alias, or compatibility re-export.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from contextlib import asynccontextmanager

import kumi.core.api.state as _state
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from kumi.core.chatbot import KumiBot
from kumi.core.features.chat.router import router as chat_router
from kumi.core.features.config import ensure_chat_model_configured, ensure_embedding_provider_not_deepseek
from kumi.core.features.config.router import router as config_router
from kumi.core.features.edge.api import apply_local_tool_confirmation_from_saved_config
from kumi.core.features.edge.router import router as edge_router
from kumi.core.features.health.router import router as health_router
from kumi.core.features.memory.embedding_state import set_embed_provider
from kumi.core.features.memory.router import router as memory_router
from kumi.core.features.monitor.router import router as monitor_router
from kumi.core.features.proactive.router import router as timers_router
from kumi.core.features.proactive.scheduler import cancel_timer, schedule_timer
from kumi.core.features.proactive.timer_tools import restore_schedules, set_timer_callbacks
from kumi.core.features.stt.router import router as stt_router
from kumi.core.features.tools.router import router as tools_router
from kumi.core.features.uploads.router import router as uploads_router
from kumi.core.platform.http.docs_middleware import DocsAccessMiddleware
from kumi.core.platform.http.task_logging import log_task_exc_on_done
from kumi.core.platform.plugins import (
    get_bot_pool,
    get_middleware_extender,
    get_route_extender,
    load_entry_point_plugins,
)
from kumi.core.platform.providers import create_provider
from kumi.core.platform.security.http_config import get_cors_settings
from kumi.logging_config import configure_logging, get_logger
from kumi.tools.bootstrap import init_kumi

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()

    from kumi.core.api.line_webhook import try_register_line_webhook

    try_register_line_webhook(app)

    set_timer_callbacks(schedule_timer, cancel_timer)
    restore_schedules()

    init_kumi()
    apply_local_tool_confirmation_from_saved_config()

    config = ensure_chat_model_configured(interactive=False)
    try:
        ensure_embedding_provider_not_deepseek(config.embedding_provider)
    except ValueError as exc:
        raise RuntimeError(
            f"{exc} Fix ~/.kumi/config.json (embedding_provider) or set KUMI_EMBEDDING_PROVIDER."
        ) from exc

    chat_provider = create_provider(config.chat_provider)
    embed_provider = (
        chat_provider
        if config.embedding_provider == config.chat_provider
        else create_provider(config.embedding_provider)
    )
    set_embed_provider(embed_provider)

    _state.set_bot(KumiBot(provider=chat_provider, model_name=config.chat_model, think=False))
    await _state.get_bot().warm_up()

    if config.proactive_mode != "off":
        from kumi.core.features.proactive.service import ProactiveMessageService

        _state.set_proactive_service(ProactiveMessageService(_state.get_bot()))
        _state.proactive_service.start()

    get_bot_pool().start_idle_sweep()

    async def _broadcast_edge_drain():
        for _k, peer in list(_state.ACTIVE_CONNECTIONS.items()):
            try:
                await peer.send_json({"type": "server_draining", "message": "Server is shutting down; reconnect."})
            except Exception:
                pass

    loop = asyncio.get_running_loop()

    def _on_sigterm() -> None:
        _state.set_server_draining(True)
        task = loop.create_task(_broadcast_edge_drain())
        log_task_exc_on_done(task, "broadcast_edge_drain")

    try:
        loop.add_signal_handler(signal.SIGTERM, _on_sigterm)
    except (NotImplementedError, RuntimeError, ValueError):
        pass

    voice_task: asyncio.Task | None = None
    voice_stop: asyncio.Event | None = None
    voice_source = None
    voice_warm_task: asyncio.Task | None = None
    if (os.environ.get("KUMI_VOICE_ENABLED") or "").strip() == "1":
        try:
            from kumi.voice.dispatch import voice_dispatch
            from kumi.voice.runtime import _warm_whisper_once, start_voice_loop

            voice_owner = (
                os.environ.get("KUMI_VOICE_OWNER_ID")
                or config.voice_owner_id
                or os.getenv("USER")
                or os.getenv("USERNAME")
                or "default"
            ).strip() or "default"
            # Warm Whisper off the lifespan critical path so /health (and dependent waiters
            # in the CLI) come up promptly even on cold installs.
            voice_warm_task = asyncio.create_task(_warm_whisper_once(), name="voice_warm_whisper")
            log_task_exc_on_done(voice_warm_task, "voice_warm_whisper")

            async def _dispatch(text: str, _owner: str = voice_owner) -> None:
                await voice_dispatch(text, owner_id=_owner)

            voice_task, voice_stop, voice_source = await start_voice_loop(
                owner_id=voice_owner,
                dispatch=_dispatch,
                cfg=config,
            )
            log_task_exc_on_done(voice_task, "voice_loop")
            logger.info("Voice loop attached (owner=%s)", voice_owner)
        except Exception as exc:
            logger.warning("Voice loop failed to start: %s", exc)
            voice_task = None
            voice_stop = None
            voice_source = None

    yield

    logger.info("Shutting down server; cleaning up...")
    if voice_task is not None:
        if voice_stop is not None:
            voice_stop.set()
        # Stop the audio source first so the blocking executor read returns
        # immediately; otherwise voice_task.cancel() leaves a zombie thread
        # holding the mic until process exit.
        if voice_source is not None:
            try:
                voice_source.stop()
            except Exception:
                pass
        voice_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await voice_task
    if voice_warm_task is not None and not voice_warm_task.done():
        voice_warm_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await voice_warm_task
    if _state.RELAY_CLIENT is not None:
        try:
            await _state.RELAY_CLIENT.stop()
        except Exception:
            pass
    if _state.proactive_service is not None:
        await _state.proactive_service.stop()
        _state.set_proactive_service(None)
    if _state.get_runtime().bot is not None:
        await _state.get_runtime().bot.provider.shutdown(_state.get_runtime().bot.model_name)


def _include_core_routers(app: FastAPI) -> None:
    app.include_router(edge_router)
    app.include_router(chat_router)
    app.include_router(timers_router)
    app.include_router(uploads_router)
    app.include_router(stt_router)
    app.include_router(config_router)
    app.include_router(memory_router)
    app.include_router(health_router)
    app.include_router(monitor_router)
    app.include_router(tools_router)


def _build_app() -> FastAPI:
    load_entry_point_plugins()

    fastapi_app = FastAPI(lifespan=lifespan)
    fastapi_app.state.runtime = _state.get_runtime()
    fastapi_app.add_middleware(DocsAccessMiddleware)
    fastapi_app.add_middleware(
        CORSMiddleware,
        **get_cors_settings("KUMI_CORS_ORIGINS", "KUMI_CORS_ALLOW_CREDENTIALS"),
    )

    for mw in get_middleware_extender().middlewares():
        if isinstance(mw, tuple):
            cls, kwargs = mw
            fastapi_app.add_middleware(cls, **(kwargs or {}))
        else:
            fastapi_app.add_middleware(mw)

    get_route_extender().mount(fastapi_app)
    _include_core_routers(fastapi_app)
    return fastapi_app


app = _build_app()


def create_app() -> FastAPI:
    """Return the configured FastAPI application (for ASGI servers and tests)."""
    return app


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, access_log=False)
