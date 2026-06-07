"""Send a transcribed voice utterance through the same chat pipeline ``/chat`` uses.

We bypass HTTP and call :func:`kumi.core.features.chat.pipeline.generate_chat_events`
directly: the voice loop already runs in the API process, so any owner-scoped
quota / auth checks would be paid twice if we did a self-call.
"""

from __future__ import annotations

from kumi.logging_config import get_logger

logger = get_logger(__name__)


def voice_session_id(owner_id: str) -> str:
    """Stable session id for a given voice owner."""
    return f"voice_{owner_id}"


async def voice_dispatch(prompt: str, *, owner_id: str) -> None:
    """Run one voice-originated chat turn end-to-end.

    Drains the event stream and surfaces assistant text via the logger so the
    operator running ``kumi --server --voice`` can see Kumi's reply on the
    server console. Does not raise on chat errors — they're logged and swallowed
    so the voice loop keeps listening.
    """
    text = (prompt or "").strip()
    if not text:
        return
    sid = voice_session_id(owner_id)
    logger.info("voice: dispatching session=%s prompt=%r", sid, text)

    from kumi.core.features.chat.pipeline import generate_chat_events

    assistant_buf: list[str] = []
    try:
        async for event in generate_chat_events(text, sid, think=False):
            if not isinstance(event, dict):
                continue
            etype = event.get("type")
            if etype == "text":
                content = event.get("content")
                if content:
                    assistant_buf.append(str(content))
            elif etype == "error":
                logger.warning("voice: chat error %s", event.get("content"))
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("voice: chat dispatch failed: %s", exc)
        return

    reply = "".join(assistant_buf).strip()
    if reply:
        logger.info("voice: reply session=%s text=%r", sid, reply)
