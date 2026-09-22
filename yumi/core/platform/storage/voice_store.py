"""Private, durable voice media; transcripts remain normal searchable messages."""

from __future__ import annotations

import hashlib
import io
import json
import time
import uuid
import wave
from pathlib import Path

from fastapi import HTTPException
from yumi.core.platform.storage.sqlite_store import SQLiteStore


class VoiceStore:
    def __init__(self, sqlite: SQLiteStore, owner: str):
        self.sqlite, self.owner = sqlite, owner
        self.root = sqlite.db_path.parent / "voice" / hashlib.sha256(owner.encode()).hexdigest()[:32]
        with sqlite.connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS voice_messages (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, session_id TEXT NOT NULL,
                event_id TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL,
                transcript TEXT NOT NULL DEFAULT '', duration_ms INTEGER,
                state TEXT NOT NULL DEFAULT 'pending', parts_json TEXT NOT NULL DEFAULT '[]',
                fingerprint TEXT NOT NULL DEFAULT '', updated_at REAL NOT NULL
            )""")
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS voice_event ON voice_messages(owner,event_id) WHERE event_id != ''"
            )

    def get(self, voice_id: str) -> dict:
        with self.sqlite.connect() as conn:
            row = conn.execute("SELECT * FROM voice_messages WHERE id=? AND owner=?", (voice_id, self.owner)).fetchone()
        if row is None:
            raise HTTPException(404, "Voice message not found.")
        result = dict(row)
        if result["event_id"]:
            event = self.sqlite.get_message(result["event_id"])
            if event is None or event["content"] != result["transcript"]:
                raise HTTPException(404, "Voice message no longer available.")
            session = self.sqlite.get_session(event["session_id"])
            if session and session.get("status") == "deleted":
                raise HTTPException(404, "Voice message no longer available.")
        result["parts"] = json.loads(result.pop("parts_json"))
        return result

    def summary(self, row: dict) -> dict:
        return {key: row.get(key) for key in ("id", "kind", "transcript", "duration_ms", "state")} | {
            "part_count": len(row.get("parts", [])),
        }

    def save_input(self, request_id: str, session_id: str, raw: bytes) -> dict:
        # Canonical UUID prevents arbitrary filenames; compare payload on every retry.
        voice_id = str(uuid.UUID(request_id))
        fingerprint = hashlib.sha256(raw).hexdigest()
        duration = wav_duration(raw, required=True)
        if duration is None or not 400 <= duration <= 65000 or len(raw) > 4 * 1024 * 1024:
            raise HTTPException(422, "Recording must be between 0.4 and 60 seconds.")
        with self.sqlite.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute("SELECT * FROM voice_messages WHERE id=?", (voice_id,)).fetchone()
            if existing:
                if (
                    existing["owner"] != self.owner
                    or existing["session_id"] != session_id
                    or existing["fingerprint"] != fingerprint
                ):
                    raise HTTPException(409, "This recording ID was already used.")
            else:
                self.root.mkdir(parents=True, exist_ok=True)
                path = self.root / f"{voice_id}-0.wav"
                path.write_bytes(raw)
                path.chmod(0o600)
                parts = [{"filename": path.name, "content_type": "audio/wav", "duration_ms": duration}]
                conn.execute(
                    "INSERT INTO voice_messages(id,owner,session_id,kind,duration_ms,parts_json,fingerprint,updated_at) VALUES(?,?,?,'user',?,?,?,?)",
                    (voice_id, self.owner, session_id, duration, json.dumps(parts), fingerprint, time.time()),
                )
        return self.get(voice_id)

    def set_transcript(self, voice_id: str, text: str):
        with self.sqlite.connect() as conn:
            conn.execute(
                "UPDATE voice_messages SET transcript=?,state='ready',updated_at=? WHERE id=? AND owner=? AND event_id=''",
                (text.strip(), time.time(), voice_id, self.owner),
            )
        return self.get(voice_id)

    def claim(self, voice_id: str, session_id: str) -> dict:
        row = self.get(voice_id)
        if row["kind"] != "user" or row["session_id"] != session_id or not row["transcript"]:
            raise HTTPException(409, "Recording does not belong to this conversation.")
        with self.sqlite.connect() as conn:
            changed = conn.execute(
                "UPDATE voice_messages SET state='sending',updated_at=? WHERE id=? AND owner=? AND event_id='' AND (state='ready' OR (state='sending' AND updated_at<?))",
                (time.time(), voice_id, self.owner, time.time() - 300),
            ).rowcount
        if not changed:
            raise HTTPException(409, "This voice message has already been sent or is being sent.")
        return row

    def release(self, voice_id: str):
        with self.sqlite.connect() as conn:
            conn.execute(
                "UPDATE voice_messages SET state='ready',updated_at=? WHERE id=? AND owner=? AND state='sending' AND event_id=''",
                (time.time(), voice_id, self.owner),
            )

    def reply_event(self, turn_id: str):
        with self.sqlite.connect() as conn:
            row = conn.execute(
                "SELECT id FROM events WHERE turn_id=? AND event_type='assistant_message' AND deleted_at IS NULL ORDER BY seq DESC LIMIT 1",
                (turn_id,),
            ).fetchone()
        if row is None:
            raise HTTPException(404, "Reply not found.")
        return self.sqlite.get_message(row["id"])

    def cached_reply(self, event_id: str):
        with self.sqlite.connect() as conn:
            row = conn.execute(
                "SELECT id FROM voice_messages WHERE event_id=? AND owner=? AND state='ready'", (event_id, self.owner)
            ).fetchone()
        return self.get(row["id"]) if row else None

    def save_reply(self, event: dict, audio_parts: list[tuple[bytes, str]], *, timing: dict | None = None) -> dict:
        voice_id = str(uuid.uuid4())
        self.root.mkdir(parents=True, exist_ok=True)
        parts = []
        try:
            for i, (raw, fmt) in enumerate(audio_parts):
                if fmt not in ("wav", "mp3", "ogg"):
                    raise HTTPException(503, "Unsupported speech audio format.")
                if fmt == "wav":
                    raw = finalize_wav(raw)
                path = self.root / f"{voice_id}-{i}.{fmt}"
                path.write_bytes(raw)
                path.chmod(0o600)
                parts.append(
                    {
                        "filename": path.name,
                        "content_type": {"wav": "audio/wav", "mp3": "audio/mpeg", "ogg": "audio/ogg"}[fmt],
                        "duration_ms": wav_duration(raw),
                    }
                )
            duration = (
                sum(p["duration_ms"] for p in parts) if all(p["duration_ms"] is not None for p in parts) else None
            )
            with self.sqlite.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                current = conn.execute(
                    "SELECT content,metadata_json,deleted_at FROM events WHERE id=?", (event["id"],)
                ).fetchone()
                if not current or current["deleted_at"] or current["content"] != event["content"]:
                    raise HTTPException(404, "Reply no longer available.")
                conn.execute(
                    "INSERT INTO voice_messages(id,owner,session_id,event_id,kind,transcript,duration_ms,state,parts_json,updated_at) VALUES(?,?,?,?,'assistant',?,?,'ready',?,?)",
                    (
                        voice_id,
                        self.owner,
                        event["session_id"],
                        event["id"],
                        event["content"],
                        duration,
                        json.dumps(parts),
                        time.time(),
                    ),
                )
                metadata = json.loads(current["metadata_json"])
                if timing:
                    metadata["voice_timing"] = timing
                metadata["voice"] = {
                    "id": voice_id,
                    "kind": "assistant",
                    "transcript": event["content"],
                    "duration_ms": duration,
                    "state": "ready",
                    "part_count": len(parts),
                }
                conn.execute("UPDATE events SET metadata_json=? WHERE id=?", (json.dumps(metadata), event["id"]))
        except BaseException:
            for part in parts:
                (self.root / part["filename"]).unlink(missing_ok=True)
            raise
        return self.get(voice_id)

    def audio(self, voice_id: str, part: int) -> tuple[Path, str]:
        row = self.get(voice_id)
        if part < 0 or part >= len(row["parts"]):
            raise HTTPException(404, "Audio part not found.")
        info = row["parts"][part]
        path = self.root / Path(info["filename"]).name
        if not path.is_file():
            raise HTTPException(404, "Audio is unavailable.")
        return path, info["content_type"]


def wav_duration(raw: bytes, *, required=False):
    try:
        with wave.open(io.BytesIO(raw), "rb") as wav:
            if wav.getcomptype() != "NONE" or wav.getnchannels() not in (1, 2) or wav.getsampwidth() != 2:
                raise ValueError("Invalid PCM recording")
            frame_bytes = wav.getnchannels() * wav.getsampwidth()
            frames = wav.readframes(wav.getnframes())
            if len(frames) % frame_bytes or (required and len(frames) != wav.getnframes() * frame_bytes):
                raise ValueError("Truncated recording")
            # Streaming TTS can leave the WAV length as 0xffffffff. Measure the
            # actual samples instead of presenting that placeholder as a duration.
            return round(len(frames) * 1000 / frame_bytes / wav.getframerate())
    except (wave.Error, EOFError, ValueError, ZeroDivisionError):
        if required:
            raise HTTPException(422, "A valid PCM WAV recording is required.") from None
        return None


def finalize_wav(raw: bytes) -> bytes:
    """Give streaming speech a finalized WAV header for native file playback."""
    try:
        with wave.open(io.BytesIO(raw), "rb") as source:
            params = source.getparams()
            frames = source.readframes(source.getnframes())
            if len(frames) == source.getnframes() * source.getnchannels() * source.getsampwidth():
                return raw
        output = io.BytesIO()
        with wave.open(output, "wb") as destination:
            destination.setparams(params._replace(nframes=0))
            destination.writeframes(frames)
        return output.getvalue()
    except (wave.Error, EOFError):
        return raw
