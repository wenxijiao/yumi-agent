"""Speech-to-text routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from kumi.core.features.uploads.service import decode_upload_payload
from kumi.core.platform.http.dependencies import CurrentIdentity
from kumi.core.platform.http.schemas import TranscribeRequest
from kumi.core.platform.plugins import get_session_scope

router = APIRouter()


@router.post("/stt/transcribe")
async def stt_transcribe_endpoint(identity: CurrentIdentity, request: TranscribeRequest):
    _ = get_session_scope().qualify_session_http(identity, request.session_id)
    raw = decode_upload_payload(request.content_base64)
    try:
        from kumi.core.features.stt import SttError, SttNotConfiguredError, transcribe_audio

        result = await transcribe_audio(raw, filename=request.filename, language=request.language)
    except SttNotConfiguredError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SttError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not result.text:
        raise HTTPException(status_code=422, detail="No speech could be transcribed from the audio.")
    return {
        "text": result.text,
        "language": result.language,
        "duration_seconds": result.duration_seconds,
    }
