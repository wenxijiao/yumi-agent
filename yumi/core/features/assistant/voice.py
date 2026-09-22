"""Account-owned voice bubbles, with cached transcription and spoken replies."""

from __future__ import annotations

import asyncio
import base64
import json
import re
import time
from dataclasses import dataclass, field
from uuid import UUID
from weakref import WeakValueDictionary

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
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


@dataclass
class _ReplyJob:
    event_id: str = ""
    frames: list[dict] = field(default_factory=list)
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    done: bool = False
    result: dict | None = None
    error: Exception | None = None
    task: asyncio.Task | None = None


_jobs: dict[str, _ReplyJob] = {}


def _reply_job(identity, body):
    store = voice_store(identity)
    event = store.reply_event(body.turn_id)
    get_session_scope().ensure_message_owned_by_identity(identity, event)
    if not event.get("voice"):
        raise HTTPException(409, "This answer was not requested as a voice reply.")
    cached = store.cached_reply(event["id"])
    if cached:
        return store, _ReplyJob(event_id=event["id"], done=True, result=store.summary(cached))
    key = f"{identity.user_id}:reply:{event['id']}"
    if key in _jobs:
        return store, _jobs[key]
    if len(_jobs) >= 8:
        raise HTTPException(429, "Voice generation is busy. Please retry shortly.")
    chunks = reply_chunks(event["content"])
    if not chunks:
        raise HTTPException(422, "This answer contains no speakable text.")
    # Reserve once for the shared job; reconnect/replay must not charge again.
    reserve_speech(identity, text="".join(chunks))
    job = _jobs[key] = _ReplyJob(event_id=event["id"])

    async def generate():
        from yumi.core.features.tts import TtsError, create_tts_provider
        from yumi.core.platform.storage.privacy_guard import lease
        from yumi.core.platform.storage.voice_store import finalize_wav, wav_duration

        started = time.perf_counter()
        try:
            # The job outlives a disconnected/paused player so the complete
            # recording remains replayable. Keep erasure protection until saved.
            with lease(identity.user_id):
                parts = []
                provider = create_tts_provider()
                first_part_ms = None
                async with asyncio.timeout(300):
                    for index, text in enumerate(chunks):
                        current = store.reply_event(body.turn_id)
                        if current["id"] != event["id"] or current["content"] != event["content"]:
                            raise HTTPException(404, "Reply no longer available.")
                        audio = await provider.synthesize(text)
                        fmt = (audio.format or "wav").lower()
                        raw = finalize_wav(audio.data) if fmt == "wav" else audio.data
                        mime = {"wav": "audio/wav", "mp3": "audio/mpeg", "ogg": "audio/ogg"}.get(fmt)
                        if not mime or not raw:
                            raise TtsError("Unsupported or empty speech audio")
                        parts.append((raw, fmt))
                        if sum(len(p[0]) for p in parts) > 32 * 1024 * 1024:
                            raise TtsError("Speech reply is too large")
                        elapsed = round((time.perf_counter() - started) * 1000)
                        if first_part_ms is None:
                            first_part_ms = elapsed
                        job.frames.append(
                            {
                                "type": "part",
                                "index": index,
                                "part_count": len(chunks),
                                "audio": raw,
                                "content_type": mime,
                                "duration_ms": wav_duration(raw),
                                "elapsed_ms": elapsed,
                            }
                        )
                        job.changed.set()
                    row = store.save_reply(
                        event,
                        parts,
                        timing={
                            "first_part_ms": first_part_ms,
                            "synthesis_ms": round((time.perf_counter() - started) * 1000),
                        },
                    )
                    job.result = store.summary(row)
        except Exception as exc:
            job.error = exc
        finally:
            job.done = True
            job.changed.set()
            _jobs.pop(key, None)

    job.task = asyncio.create_task(generate(), name="yumi-reply-voice")
    return store, job


@router.post("/reply")
async def prepare_reply_voice(identity: CurrentIdentity, body: VoiceReply):
    """Compatible complete-response endpoint for older apps and channels."""
    _, job = _reply_job(identity, body)
    if job.task:
        await asyncio.shield(job.task)
    if job.error:
        if isinstance(job.error, HTTPException):
            raise job.error
        raise HTTPException(503, "Voice generation is temporarily unavailable. Please retry.") from job.error
    return job.result


@router.post("/reply/stream")
async def stream_reply_voice(identity: CurrentIdentity, body: VoiceReply):
    """Send complete playable sentence groups as soon as each is ready."""
    store, job = _reply_job(identity, body)

    async def events():
        cursor = 0
        while True:
            if store.sqlite.get_message(job.event_id) is None:
                yield '{"type":"error","message":"Reply no longer available."}\n'
                return
            job.changed.clear()
            while cursor < len(job.frames):
                frame = job.frames[cursor]
                cursor += 1
                yield json.dumps({**frame, "audio": base64.b64encode(frame["audio"]).decode()}) + "\n"
            if job.done:
                if job.error:
                    yield json.dumps({"type": "error", "message": "Voice generation could not be completed."}) + "\n"
                else:
                    yield json.dumps({"type": "ready", "voice": job.result}) + "\n"
                return
            try:
                await asyncio.wait_for(job.changed.wait(), timeout=10)
            except TimeoutError:
                yield '{"type":"keepalive"}\n'

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-store",
            "X-Accel-Buffering": "no",
        },
    )


def reply_chunks(markdown: str) -> list[str]:
    """A short first sentence group, then larger groups for natural prosody."""
    chunks = spoken_chunks(markdown, size=600)
    if not chunks:
        return []
    first = chunks.pop(0)
    boundaries = [m.end() for m in re.finditer(r"[。！？]|[.!?](?:\s+|$)", first[:220]) if m.end() >= 12]
    if boundaries:
        end = boundaries[0]
    elif len(first) > 220:
        end = max(first.rfind(" ", 100, 220), first.rfind("，", 100, 220), first.rfind("、", 100, 220))
        end = end + 1 if end >= 100 else 220
    else:
        end = len(first)
    remainder = first[end:].strip()
    return [first[:end].strip()] + ([remainder] if remainder else []) + chunks


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
