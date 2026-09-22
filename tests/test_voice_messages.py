from __future__ import annotations

import asyncio
import base64
import io
import json
import uuid
import wave
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from yumi.core.features.assistant import voice as voice_api
from yumi.core.features.chat import router as chat
from yumi.core.platform.http.dependencies import current_identity_dependency
from yumi.core.platform.http.schemas import ChatRequest
from yumi.core.platform.plugins import Identity
from yumi.core.platform.runtime.assistant_context import message_media
from yumi.core.platform.storage.sqlite_store import SQLiteStore
from yumi.core.platform.storage.voice_store import VoiceStore, wav_duration


def wav(ms=1000, sample=0):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(bytes([sample, 0]) * (16 * ms))
    return buf.getvalue()


@pytest.fixture
def store(tmp_path):
    return VoiceStore(SQLiteStore(tmp_path / "yumi.db"), "alice")


def ready(store, text="Check the weather"):
    row = store.save_input(str(uuid.uuid4()), "alice_personal", wav())
    return store.set_transcript(row["id"], text)


def save_turn(store, row, turn="turn1"):
    token = message_media.set({"input": store.summary(row), "reply": True})
    try:
        store.sqlite.upsert_event_from_message(
            {
                "id": "user-" + turn,
                "role": "user",
                "content": row["transcript"],
                "session_id": row["session_id"],
                "turn_id": turn,
            }
        )
        store.sqlite.upsert_event_from_message(
            {
                "id": "reply-" + turn,
                "role": "assistant",
                "content": "Sunny today.",
                "session_id": row["session_id"],
                "turn_id": turn,
            }
        )
    finally:
        message_media.reset(token)
    return store.sqlite.get_message("reply-" + turn)


def test_original_audio_transcript_and_duration_survive_restart(store):
    row = ready(store)
    save_turn(store, row)
    reopened = VoiceStore(SQLiteStore(store.sqlite.db_path), "alice")
    assert reopened.audio(row["id"], 0)[0].read_bytes() == wav()
    assert reopened.summary(reopened.get(row["id"]))["duration_ms"] == 1000
    assert reopened.sqlite.get_message("user-turn1")["voice"]["transcript"] == "Check the weather"


def test_upload_retry_is_idempotent_and_rejects_changed_payload_or_session(store):
    row = ready(store)
    assert store.save_input(row["id"], row["session_id"], wav())["transcript"] == row["transcript"]
    for sid, raw in [("elsewhere", wav()), (row["session_id"], wav(sample=1))]:
        with pytest.raises(HTTPException) as error:
            store.save_input(row["id"], sid, raw)
        assert error.value.status_code == 409


@pytest.mark.parametrize("raw", [b"invalid", wav(200), wav(66000), wav()[:-100]])
def test_invalid_short_long_or_truncated_audio_is_rejected(store, raw):
    with pytest.raises(HTTPException) as error:
        store.save_input(str(uuid.uuid4()), "alice_personal", raw)
    assert error.value.status_code == 422


def test_other_account_cannot_read_or_claim_recording(store):
    row = ready(store)
    other = VoiceStore(store.sqlite, "bob")
    with pytest.raises(HTTPException) as error:
        other.audio(row["id"], 0)
    assert error.value.status_code == 404
    with pytest.raises(HTTPException):
        other.save_input(row["id"], row["session_id"], wav())


def test_claim_is_exclusive_and_committed_message_cannot_be_sent_twice(store):
    row = ready(store)
    store.claim(row["id"], row["session_id"])
    with pytest.raises(HTTPException):
        store.claim(row["id"], row["session_id"])
    save_turn(store, row)
    store.release(row["id"])
    with pytest.raises(HTTPException):
        store.claim(row["id"], row["session_id"])


def test_reimport_does_not_attach_new_voice_to_old_messages(store):
    row = ready(store)
    token = message_media.set({"input": store.summary(row), "reply": True})
    try:
        store.sqlite.upsert_event_from_message(
            {"id": "old", "role": "user", "content": row["transcript"], "session_id": row["session_id"]}
        )
    finally:
        message_media.reset(token)
    assert store.sqlite.get_message("old")["voice"] is None
    assert store.get(row["id"])["event_id"] == ""


def test_reply_is_saved_with_text_and_all_audio_parts_and_hidden_on_delete(store):
    row = ready(store)
    event = save_turn(store, row)
    output = store.save_reply(event, [(wav(500), "wav"), (wav(800), "wav")])
    assert output["duration_ms"] == 1300
    assert store.summary(output)["part_count"] == 2
    assert store.cached_reply(event["id"])["id"] == output["id"]
    assert store.sqlite.get_message(event["id"])["voice"]["id"] == output["id"]
    store.sqlite.delete_message(event["id"])
    with pytest.raises(HTTPException) as error:
        store.audio(output["id"], 0)
    assert error.value.status_code == 404
    store.sqlite.delete_message("user-turn1")
    with pytest.raises(HTTPException):
        store.audio(row["id"], 0)


def test_voice_http_upload_auth_playback_and_cached_reply(monkeypatch, store):
    from yumi.core.features import stt, tts

    user = [Identity(user_id="alice")]

    def scope():
        def own(identity, event):
            if not event["session_id"].startswith(identity.user_id + "_"):
                raise HTTPException(404)

        return SimpleNamespace(
            qualify_session_http=lambda identity, sid: identity.user_id + "_" + sid,
            ensure_message_owned_by_identity=own,
        )

    monkeypatch.setattr(voice_api, "voice_store", lambda identity: VoiceStore(store.sqlite, identity.user_id))
    monkeypatch.setattr(voice_api, "get_session_scope", scope)
    transcribed, spoken = [], []

    async def transcribe(raw, **kwargs):
        transcribed.append(raw)
        return SimpleNamespace(text="Check the weather")

    async def synthesize(text):
        spoken.append(text)
        return SimpleNamespace(data=wav(), format="wav")

    monkeypatch.setattr(stt, "transcribe_audio", transcribe)
    monkeypatch.setattr(tts, "create_tts_provider", lambda: SimpleNamespace(synthesize=synthesize))
    app = FastAPI()
    app.include_router(voice_api.router, prefix="/assistant")
    app.dependency_overrides[current_identity_dependency] = lambda: user[0]
    with TestClient(app) as client:
        body = {
            "request_id": str(uuid.uuid4()),
            "session_id": "personal",
            "content_base64": base64.b64encode(wav()).decode(),
        }
        response = client.post("/assistant/voice", json=body)
        assert response.status_code == 200, response.text
        row = response.json()
        assert client.post("/assistant/voice", json=body).json() == row
        assert len(transcribed) == 1
        assert client.get("/assistant/voice/" + row["id"] + "/audio").content == wav()
        assert client.get("/assistant/voice/" + row["id"] + "/audio?part=9").status_code == 404
        event = save_turn(store, store.get(row["id"]))
        result = client.post("/assistant/voice/reply", json={"turn_id": "turn1"})
        assert result.status_code == 200, result.text
        assert client.post("/assistant/voice/reply", json={"turn_id": "turn1"}).json() == result.json()
        assert spoken == ["Sunny today."]
        user[0] = Identity(user_id="bob")
        assert client.get("/assistant/voice/" + row["id"] + "/audio").status_code == 404
        assert client.post("/assistant/voice/reply", json={"turn_id": event["turn_id"]}).status_code == 404


def test_chat_uses_saved_transcript_and_never_releases_another_requests_claim(monkeypatch, store):
    row = ready(store)
    monkeypatch.setattr(
        chat,
        "get_memory_factory",
        lambda: SimpleNamespace(get_for_identity=lambda _: SimpleNamespace(sqlite=store.sqlite)),
    )
    monkeypatch.setattr(chat, "get_session_scope", lambda: SimpleNamespace(qualify_session_http=lambda _, sid: sid))
    monkeypatch.setattr(chat, "audit_event", lambda *args, **kwargs: None)
    seen = []

    async def events(prompt, sid, think=False):
        seen.append(prompt)
        save_turn(store, row)
        yield {"type": "text", "content": "Sunny today."}

    monkeypatch.setattr(chat, "generate_chat_events", events)

    async def run():
        identity = Identity(user_id="alice")
        store.claim(row["id"], row["session_id"])
        response = await chat.chat_endpoint(
            None, identity, ChatRequest(prompt="Tampered prompt", session_id=row["session_id"], voice_id=row["id"])
        )
        body = "".join(
            [item if isinstance(item, str) else bytes(item).decode() async for item in response.body_iterator]
        )
        assert json.loads(body)["code"] == "409"
        assert store.get(row["id"])["state"] == "sending"
        assert not seen
        store.release(row["id"])
        response = await chat.chat_endpoint(
            None,
            identity,
            ChatRequest(prompt="Tampered prompt", session_id=row["session_id"], voice_id=row["id"], reply_voice=True),
        )
        assert "Sunny" in "".join(
            [item if isinstance(item, str) else bytes(item).decode() async for item in response.body_iterator]
        )
        assert message_media.get() is None
        with pytest.raises(HTTPException) as error:
            await chat.chat_endpoint(
                None, identity, ChatRequest(prompt="again", session_id=row["session_id"], voice_id=row["id"])
            )
        assert error.value.status_code == 409

    asyncio.run(run())
    assert seen == [row["transcript"]]


def test_spoken_chunks_preserve_unicode_and_omit_code_and_urls():
    text = "Weather 😀. " * 500
    chunks = voice_api.spoken_chunks(text + "\n```python\nsecret()\n```\nhttps://example.com")
    assert all(len(chunk) <= 1200 for chunk in chunks)
    assert " ".join(chunks) == text.strip()
    assert voice_api.spoken_chunks("```python\nunfinished()") == []


def test_streaming_tts_wav_uses_actual_sample_duration(store):
    streaming = bytearray(wav(1200))
    streaming[4:8] = b"\xff" * 4
    streaming[40:44] = b"\xff" * 4
    assert wav_duration(bytes(streaming)) == 1200
    row = ready(store)
    event = save_turn(store, row)
    saved = store.save_reply(event, [(bytes(streaming), "wav")])
    assert saved["duration_ms"] == 1200
    persisted = store.audio(saved["id"], 0)[0].read_bytes()
    assert wav_duration(persisted, required=True) == 1200
    assert persisted[44:] == bytes(streaming)[44:]


def test_streamed_reply_is_playable_before_remaining_synthesis_and_shared_on_reconnect(monkeypatch, store):
    from yumi.core.features import tts

    row = ready(store)
    event = save_turn(store, row)
    monkeypatch.setattr(voice_api, "voice_store", lambda _: store)
    monkeypatch.setattr(
        voice_api, "get_session_scope", lambda: SimpleNamespace(ensure_message_owned_by_identity=lambda *_: None)
    )
    monkeypatch.setattr(voice_api, "reply_chunks", lambda _: ["First sentence.", "Second sentence."])
    reservations = []
    monkeypatch.setattr(voice_api, "reserve_speech", lambda *a, **kw: reservations.append(kw))

    async def run():
        release = asyncio.Event()
        calls = []

        async def synthesize(text):
            calls.append(text)
            if len(calls) == 2:
                await release.wait()
            return SimpleNamespace(data=wav(500), format="wav")

        monkeypatch.setattr(tts, "create_tts_provider", lambda: SimpleNamespace(synthesize=synthesize))
        identity = Identity(user_id="_local")
        response = await voice_api.stream_reply_voice(identity, voice_api.VoiceReply(turn_id="turn1"))
        iterator = response.body_iterator
        first = json.loads(await anext(iterator))
        assert first["type"] == "part"
        assert wav_duration(base64.b64decode(first["audio"])) == 500
        assert store.cached_reply(event["id"]) is None
        # Disconnecting playback leaves the account-owned synthesis running.
        await iterator.aclose()
        _, same_job = voice_api._reply_job(identity, voice_api.VoiceReply(turn_id="turn1"))
        assert len(reservations) == 1
        release.set()
        await same_job.task
        assert same_job.result["part_count"] == 2
        assert len(calls) == 2
        cached = await voice_api.prepare_reply_voice(identity, voice_api.VoiceReply(turn_id="turn1"))
        assert cached["id"] == same_job.result["id"]
        assert len(reservations) == 1

    asyncio.run(run())


def test_reply_chunking_keeps_text_and_uses_a_short_complete_first_sentence():
    text = "This is the first sentence. " + "This is the rest of the response. " * 50
    chunks = voice_api.reply_chunks(text)
    assert chunks[0] == "This is the first sentence."
    assert all(len(chunk) <= 600 for chunk in chunks)
    assert " ".join(chunks) == text.strip()
