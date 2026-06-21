"""Send a transcribed voice utterance through the same chat pipeline ``/chat`` uses.

We bypass HTTP and call :func:`yumi.core.features.chat.pipeline.generate_chat_events`
directly: the voice loop already runs in the API process, so any owner-scoped
quota / auth checks would be paid twice if we did a self-call.
"""

from __future__ import annotations

import asyncio

from yumi.logging_config import get_logger

logger = get_logger(__name__)


def voice_session_id(owner_id: str) -> str:
    """Stable session id for a given voice owner."""
    return f"voice_{owner_id}"


async def _speak_voice_reply(reply: str) -> None:
    """Speak the assistant's reply aloud.

    Voice mode always talks back: use the configured TTS provider, or fall back
    to the OS system voice when TTS hasn't been set up — so saying the wake word
    always gets a spoken answer. Playback runs in a worker thread so the voice
    loop keeps listening; any failure is logged, never raised.
    """
    from yumi.core.features.config import load_model_config
    from yumi.core.features.tts.base import TtsNotConfiguredError
    from yumi.core.features.tts.factory import create_tts_provider
    from yumi.core.features.tts.playback import play_audio
    from yumi.core.features.tts.system_provider import SystemTtsProvider

    try:
        provider = create_tts_provider(load_model_config())
    except TtsNotConfiguredError:
        provider = SystemTtsProvider()
    try:
        audio = await provider.synthesize(reply)
        await asyncio.to_thread(play_audio, audio)
    except Exception as exc:  # provider / playback errors must not kill the loop
        logger.warning("voice: spoken reply failed: %s", exc)


async def voice_dispatch(prompt: str, *, owner_id: str) -> None:
    """Run one voice-originated chat turn end-to-end.

    Drains the event stream and surfaces assistant text via the logger so the
    operator running ``yumi --server --voice`` can see Yumi's reply on the
    server console. Does not raise on chat errors — they're logged and swallowed
    so the voice loop keeps listening.
    """
    text = (prompt or "").strip()
    if not text:
        return
    sid = voice_session_id(owner_id)
    logger.info("voice: dispatching session=%s prompt=%r", sid, text)

    from yumi.core.features.chat.pipeline import generate_chat_events

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
        await _speak_voice_reply(reply)
