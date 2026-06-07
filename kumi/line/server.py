"""Standalone LINE webhook server (topology B: sidecar to core Kumi HTTP API)."""

from __future__ import annotations

import asyncio
import os

import uvicorn
from fastapi import FastAPI, Request, Response

from kumi.core.features.config.line import get_line_bot_port, get_line_channel_secret
from kumi.core.platform.http.task_logging import log_task_exc_on_done
from kumi.logging_config import configure_logging, get_logger

_LOG = get_logger(__name__)


def build_line_app() -> FastAPI:
    app = FastAPI(title="Kumi LINE webhook")
    # Hold strong refs so background tasks aren't GC'd between webhook calls.
    pending_tasks: set[asyncio.Task] = set()
    app.state.line_pending_tasks = pending_tasks

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "kumi-line-webhook"}

    @app.post("/line/webhook")
    async def line_webhook(request: Request) -> Response:
        if not get_line_channel_secret():
            return Response(status_code=503, content="LINE not configured")
        body = await request.body()
        sig = request.headers.get("X-Line-Signature")
        from kumi.line.handlers import process_line_events, verify_and_parse_line_webhook

        try:
            events, line_client = verify_and_parse_line_webhook(body, sig)
        except PermissionError:
            return Response(status_code=401, content="invalid signature")
        except ValueError as exc:
            return Response(status_code=400, content=str(exc)[:500])
        except RuntimeError as exc:
            return Response(status_code=503, content=str(exc)[:500])

        if events:
            task = asyncio.create_task(process_line_events(events, line_client, use_http=True))
            pending_tasks.add(task)
            task.add_done_callback(pending_tasks.discard)
            log_task_exc_on_done(task, "line_webhook")
        return Response(status_code=200)

    return app


def run_line_bot_sync() -> None:
    configure_logging()
    port = get_line_bot_port()
    host = os.getenv("LINE_BOT_HOST", "0.0.0.0").strip() or "0.0.0.0"
    app = build_line_app()
    _LOG.info("Starting LINE webhook on %s:%s (set webhook URL to http(s)://<host>:%s/line/webhook)", host, port, port)
    uvicorn.run(app, host=host, port=port, log_level="info")
