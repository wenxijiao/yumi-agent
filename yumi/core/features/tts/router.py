"""Text-to-speech routes (spoken replies for the web UI)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from yumi.core.platform.http.dependencies import CurrentIdentity
from yumi.core.platform.http.schemas import TtsRequest
from yumi.core.platform.plugins import get_session_scope

router = APIRouter()


@router.post("/tts/synthesize")
async def tts_synthesize_endpoint(identity: CurrentIdentity, request: TtsRequest):
    """Synthesize *text* to audio bytes playable in a browser ``<audio>`` element."""
    _ = get_session_scope().qualify_session_http(identity, request.session_id)
    text = (request.text or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="Text cannot be empty.")
    try:
        from yumi.core.features.tts import TtsError, TtsNotConfiguredError, create_tts_provider

        provider = create_tts_provider()
        audio = await provider.synthesize(text, voice=request.voice, language=request.language)
    except TtsNotConfiguredError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TtsError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(
        content=audio.data,
        media_type=f"audio/{audio.format or 'wav'}",
        headers={"Cache-Control": "no-store"},
    )
