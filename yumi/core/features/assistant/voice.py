"""Account-owned voice bubbles, with cached transcription and spoken replies."""

from __future__ import annotations

import asyncio
import re
from uuid import UUID
from weakref import WeakValueDictionary

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from yumi.core.platform.http.dependencies import CurrentIdentity
from yumi.core.platform.plugins import get_memory_factory, get_session_scope
from yumi.core.platform.plugins.usage_guard import reserve_speech
from yumi.core.platform.storage.voice_store import VoiceStore

router = APIRouter(prefix="/voice", tags=["Voice messages"])
_locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()


def voice_store(identity):
    return VoiceStore(get_memory_factory().get_for_identity(identity).sqlite, identity.user_id)


class VoiceUpload(BaseModel):
    request_id: UUID
    session_id: str
    content_base64: str = Field(max_length=6 * 1024 * 1024)


class VoiceReply(BaseModel):
    turn_id: str = Field(min_length=1, max_length=160)


@router.post("")
async def upload_voice(identity: CurrentIdentity, body: VoiceUpload):
    from yumi.core.features.stt import SttError, transcribe_audio
    from yumi.core.features.uploads.service import decode_upload_payload

    sid = get_session_scope().qualify_session_http(identity, body.session_id)
    store = voice_store(identity)
    key = f"{identity.user_id}:input:{body.request_id}"
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        row = store.save_input(str(body.request_id), sid, decode_upload_payload(body.content_base64))
        if not row["transcript"]:
            reserve_speech(identity, audio=(store.audio(row["id"], 0)[0]).read_bytes())
            try:
                result = await transcribe_audio((store.audio(row["id"], 0)[0]).read_bytes(), filename="voice.wav")
            except SttError as exc:
                raise HTTPException(503, "Voice transcription is temporarily unavailable. Please retry.") from exc
            if not result.text.strip():
                raise HTTPException(422, "No speech could be transcribed.")
            row = store.set_transcript(row["id"], result.text)
    return store.summary(row)


@router.get("/{voice_id}/audio")
async def get_voice_audio(identity: CurrentIdentity, voice_id: UUID, part: int = Query(0, ge=0)):
    path, mime = voice_store(identity).audio(str(voice_id), part)
    return FileResponse(path, media_type=mime, headers={"Cache-Control": "private, no-store"})


@router.post("/reply")
async def prepare_reply_voice(identity: CurrentIdentity, body: VoiceReply):
    from yumi.core.features.tts import TtsError, create_tts_provider

    store = voice_store(identity)
    event = store.reply_event(body.turn_id)
    get_session_scope().ensure_message_owned_by_identity(identity, event)
    if not event.get("voice"):
        raise HTTPException(409, "This answer was not requested as a voice reply.")
    key = f"{identity.user_id}:reply:{event['id']}"
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        cached = store.cached_reply(event["id"])
        if cached:
            return store.summary(cached)
        chunks = spoken_chunks(event["content"])
        if not chunks:
            raise HTTPException(422, "This answer contains no speakable text.")
        reserve_speech(identity, text="".join(chunks))
        try:
            provider = create_tts_provider()
            parts = []
            for text in chunks:
                audio = await provider.synthesize(text)
                parts.append((audio.data, (audio.format or "wav").lower()))
            row = store.save_reply(event, parts)
        except TtsError as exc:
            raise HTTPException(503, "Voice generation is temporarily unavailable. Please retry.") from exc
    return store.summary(row)


def spoken_chunks(markdown: str, size: int = 1200) -> list[str]:
    text = re.sub(r"```[\s\S]*?(?:```|$)", "", markdown)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"(^|\n)\s*[#>]+\s*", "\n", text)
    text = re.sub(r"[*_`~]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    chunks = []
    while text:
        end = min(len(text), size)
        if end < len(text):
            for i in range(end - 1, end // 2, -1):
                if text[i] in " .!?。！？":
                    end = i + 1
                    break
        chunks.append(text[:end].strip())
        text = text[end:].strip()
    return chunks
