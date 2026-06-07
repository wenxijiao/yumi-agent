"""Optional in-core LINE webhook (``YUMI_LINE_INCORE=1``)."""

from __future__ import annotations

import asyncio

from fastapi import FastAPI, Request, Response
from yumi.core.features.config.line import get_line_channel_secret
from yumi.core.platform.http.task_logging import log_task_exc_on_done


def try_register_line_webhook(app: FastAPI) -> None:
    """Register ``POST /line/webhook`` once when in-core LINE mode is enabled."""
    if getattr(app.state, "line_webhook_registered", False):
        return
    from yumi.core.features.config.line import line_incore_enabled

    if not line_incore_enabled() or not get_line_channel_secret():
        return
    app.state.line_webhook_registered = True

    @app.post("/line/webhook")
    async def line_webhook_incore(request: Request) -> Response:
        body = await request.body()
        sig = request.headers.get("X-Line-Signature")
        from yumi.line.handlers import process_line_events, verify_and_parse_line_webhook

        try:
            events, line_client = verify_and_parse_line_webhook(body, sig)
        except PermissionError:
            return Response(status_code=401, content="invalid signature")
        except ValueError as exc:
            return Response(status_code=400, content=str(exc)[:500])
        except RuntimeError as exc:
            return Response(status_code=503, content=str(exc)[:500])

        # LINE retries any webhook that doesn't respond in ~1s. Run the chat
        # turn off the request path so we ack within the window.
        if events:
            task = asyncio.create_task(process_line_events(events, line_client, use_http=False))
            log_task_exc_on_done(task, "line_webhook_incore")
        return Response(status_code=200)
