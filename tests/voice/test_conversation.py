from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import time
from types import SimpleNamespace

import httpx
import pytest
from yumi.voice.client import VoiceConnection
from yumi.voice.conversation import VoiceSession, confirmation_decision


class Audio:
    def __init__(self):
        self.interruptions = 0
        self.played = []
        self.cues = []

    def interrupt(self):
        self.interruptions += 1

    async def play(self, data):
        self.played.append(data)

    async def cue(self, kind):
        self.cues.append(kind)

    def close(self):
        pass


class Wake:
    def __init__(self):
        self.calls = 0

    def reset(self):
        pass

    def process(self, frame):
        self.calls += 1
        return self.calls == 1


def session(handler=None):
    client = httpx.AsyncClient(
        base_url="https://example.test", transport=httpx.MockTransport(handler or (lambda _: httpx.Response(200)))
    )
    return VoiceSession(
        VoiceConnection("https://example.test"),
        Audio(),
        Wake(),
        client=client,
        silence_ms=800,  # Explicit fast endpoint for existing state-machine tests.
        vad=SimpleNamespace(is_speech=lambda frame, _: frame[0] != 0),
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("确认。", "allow"),
        ("Yes, please!", "allow"),
        ("不要", "deny"),
        ("不确认", None),
        ("yes but don't delete", None),
        ("明天天气好吗", None),
    ],
)
def test_confirmation_requires_unambiguous_answer(text, expected):
    assert confirmation_decision(text) == expected


def test_wake_silence_does_not_upload_and_followup_does_not_need_wake():
    async def run():
        voice = session()
        recordings = []

        async def turn(wav, previous=None):
            recordings.append(wav)
            voice.deadline = time.monotonic() + 20

        voice.turn = turn
        silence, speech = bytes(3200), b"\x01\x10" * 1600
        await voice.feed(silence)  # Wake
        for _ in range(90):
            await voice.feed(silence)
        assert not recordings
        for _ in range(2):
            for frame in [speech] * 5 + [silence] * 8:
                await voice.feed(frame)
            await asyncio.sleep(0)
        assert len(recordings) == 2
        assert voice.wake.calls == 1
        await voice.close()

    asyncio.run(run())


def test_barge_in_stops_audio_and_cancels_turn_without_new_wake():
    async def run():
        voice = session()
        cancelled = asyncio.Event()

        async def old_turn():
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        voice.task = asyncio.create_task(old_turn())
        await asyncio.sleep(0)
        for _ in range(3):
            await voice.feed(b"\x01\x10" * 1600)
        await asyncio.sleep(0)
        assert cancelled.is_set()
        assert voice.audio.interruptions == 1
        assert voice.collecting
        assert voice.wake.calls == 0
        await voice.close()

    asyncio.run(run())


def test_account_pipeline_streams_parts_and_does_not_replay_on_ready():
    calls = []

    def handler(request):
        body = json.loads(request.content) if request.content else {}
        calls.append((request.url.path, body))
        if request.url.path == "/assistant":
            return httpx.Response(200, json={"conversation": {"session_id": "personal", "revision": 4}})
        if request.url.path == "/assistant/voice":
            return httpx.Response(200, json={"id": "recording", "transcript": "hello"})
        if request.url.path == "/chat":
            assert body["personal"] and body["reply_voice"] and body["revision"] == 4
            assert body["voice_id"] == "recording" and len(body["client_request_id"]) == 36
            return httpx.Response(200, text='{"type":"turn_phase","turn_id":"turn"}\n{"type":"text","content":"Hi"}\n')
        if request.url.path == "/assistant/voice/reply/stream":
            return httpx.Response(
                200,
                text=json.dumps({"type": "part", "index": 0, "audio": base64.b64encode(b"audio").decode()})
                + "\n"
                + json.dumps({"type": "ready", "voice": {"id": "reply", "part_count": 1}})
                + "\n",
            )
        raise AssertionError(request.url)

    async def run():
        voice = session(handler)
        await voice.turn(b"wav")
        assert voice.audio.played == [b"audio"]
        assert voice.deadline > time.monotonic()
        await voice.close()

    asyncio.run(run())


def test_confirmation_answer_does_not_cancel_the_waiting_tool():
    async def run():
        voice = session()
        voice.task = asyncio.create_task(asyncio.sleep(100))
        voice.confirmation = asyncio.get_running_loop().create_future()
        for frame in [b"\x01\x10" * 1600] * 5 + [bytes(3200)] * 8:
            await voice.feed(frame)
        assert voice.confirmation.done()
        assert (await voice.confirmation).startswith(b"RIFF")
        assert not voice.task.cancelled()
        voice.task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await voice.task
        await voice.close()

    asyncio.run(run())


def test_expired_followup_requires_wake_again():
    async def run():
        voice = session()
        voice.wake.calls = 1
        voice.deadline = time.monotonic() - 1
        for _ in range(4):
            await voice.feed(b"\x01\x10" * 1600)
        assert voice.task is None
        assert voice.wake.calls == 5
        await voice.close()

    asyncio.run(run())


def test_cancelling_http_turn_sends_targeted_server_cancel():
    async def run():
        started = asyncio.Event()
        calls = []

        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                started.set()
                yield b'{"type":"turn_phase","turn_id":"turn"}\n'
                await asyncio.Event().wait()

        def handler(request):
            body = json.loads(request.content) if request.content else {}
            calls.append((request.url.path, body))
            if request.url.path == "/assistant":
                return httpx.Response(200, json={"session_id": "personal"})
            if request.url.path == "/assistant/voice":
                return httpx.Response(200, json={"id": "voice", "transcript": "hi"})
            if request.url.path == "/chat":
                return httpx.Response(200, stream=Stream())
            if request.url.path == "/chat/cancel":
                return httpx.Response(200, json={"status": "cancelled"})
            raise AssertionError(request.url)

        voice = session(handler)
        task = asyncio.create_task(voice.turn(b"wav"))
        await started.wait()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        chat = next(body for path, body in calls if path == "/chat")
        assert calls[-1] == ("/chat/cancel", {"client_request_id": chat["client_request_id"]})
        assert not voice.audio.played
        assert voice._cancel_error is None
        await voice.close()

    asyncio.run(run())


def test_unknown_confirmation_reprompts_instead_of_granting():
    async def run():
        decisions = []
        prompts = []
        transcripts = iter(["not sure", "确认"])

        def handler(request):
            if request.url.path == "/assistant/voice":
                return httpx.Response(200, json={"transcript": next(transcripts)})
            if request.url.path == "/tools/confirm":
                decisions.append(json.loads(request.content))
                return httpx.Response(200, json={"ok": True})
            raise AssertionError(request.url)

        voice = session(handler)

        async def speak(text, session_id):
            prompts.append(text)
            voice.confirmation.set_result(b"wav")

        voice.speak = speak
        await voice.confirm(
            {"call_id": "specific-action", "action_summary": "开灯", "arguments": {"room": "bedroom"}}, "personal"
        )
        assert len(prompts) == 2
        assert "bedroom" in prompts[0]
        assert decisions == [{"call_id": "specific-action", "decision": "allow"}]
        await voice.close()

    asyncio.run(run())


def test_second_interruption_does_not_bypass_unfinished_server_cancellation():
    async def run():
        cancellation_started, release = asyncio.Event(), asyncio.Event()
        chat_started = asyncio.Event()
        chats = []

        class Stream(httpx.AsyncByteStream):
            async def __aiter__(self):
                chat_started.set()
                yield b'{"type":"turn_phase","turn_id":"turn"}\n'
                await asyncio.Event().wait()

        async def handler(request):
            if request.url.path == "/assistant":
                return httpx.Response(200, json={"session_id": "personal"})
            if request.url.path == "/assistant/voice":
                return httpx.Response(200, json={"id": "voice", "transcript": "hi"})
            if request.url.path == "/chat":
                chats.append(request)
                return httpx.Response(200, stream=Stream())
            if request.url.path == "/chat/cancel":
                cancellation_started.set()
                await release.wait()
                return httpx.Response(200, json={"status": "cancelled"})
            raise AssertionError(request.url)

        voice = session(handler)
        first = asyncio.create_task(voice.turn(b"first"))
        await chat_started.wait()
        first.cancel()
        await cancellation_started.wait()
        second = asyncio.create_task(voice.turn(b"second", first))
        await asyncio.sleep(0)
        second.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await second
        third = asyncio.create_task(voice.turn(b"third", second))
        await asyncio.sleep(0.01)
        assert len(chats) == 1
        chat_started.clear()
        release.set()
        await asyncio.wait_for(chat_started.wait(), 1)
        assert len(chats) == 2
        third.cancel()
        for task in [first, third]:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        assert voice._cancel_error is None
        await voice.close()

    asyncio.run(run())


def test_early_confirmation_answer_suppresses_late_prompt_audio():
    async def run():
        voice = None

        async def handler(request):
            assert request.url.path == "/tts/synthesize"
            # User starts speaking before the TTS request has returned.
            voice._speech_epoch += 1
            return httpx.Response(200, content=b"late-prompt")

        voice = session(handler)
        await voice.speak("Confirm?", "personal")
        assert not voice.audio.played
        await voice.close()

    asyncio.run(run())


@pytest.mark.parametrize("phrase", ["晚安", "先这样吧", "结束对话", "Good night!", "Hey Yumi, goodbye."])
def test_goodnight_ends_followup_without_chat_or_spoken_cloud_reply(phrase):
    async def run():
        calls = []

        def handler(request):
            calls.append(request.url.path)
            if request.url.path == "/assistant":
                return httpx.Response(200, json={"session_id": "personal"})
            if request.url.path == "/assistant/voice":
                return httpx.Response(200, json={"id": "voice", "transcript": phrase})
            raise AssertionError(request.url)

        voice = session(handler)
        await voice.turn(b"wav")
        assert voice.deadline == 0 and voice._ended
        assert voice.audio.cues == ["sleep"]
        assert calls == ["/assistant", "/assistant/voice"]
        # Ordinary speech cannot reopen the follow-up window.
        voice.wake.calls = 1
        await voice.feed(b"\x01\x10" * 1600)
        assert voice.task is None
        await voice.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "phrase", ["帮我给妈妈说晚安", "good night是什么歌", "停止音乐", "pause the music", "不要结束对话"]
)
def test_control_phrases_do_not_match_embedded_or_negated_requests(phrase):
    from yumi.voice.conversation import conversation_control

    assert conversation_control(phrase) is None


def test_microphone_pause_requests_device_release_instead_of_standby():
    async def run():
        voice = session()
        await voice.standby(pause=True)
        assert voice.pause_requested
        assert voice.audio.cues == ["pause"]
        assert voice.deadline == 0
        await voice.close()

    asyncio.run(run())


def test_wake_has_immediate_local_audio_feedback_and_does_not_call_server():
    async def run():
        voice = session(lambda _: pytest.fail("Wake cue must be local"))
        await voice.feed(bytes(3200))
        await asyncio.sleep(0)
        assert voice.audio.cues == ["wake"]
        assert voice._awake and not voice._ended
        await voice.close()

    asyncio.run(run())


def test_empty_transcription_422_is_recoverable_and_not_a_chat(capsys):
    async def run():
        def handler(request):
            if request.url.path == "/assistant":
                return httpx.Response(200, json={"session_id": "personal"})
            if request.url.path == "/assistant/voice":
                return httpx.Response(422, json={"detail": "No speech could be transcribed."})
            raise AssertionError(request.url)

        voice = session(handler)
        await voice.turn(b"wav")
        await asyncio.sleep(0)
        assert voice.audio.cues == ["retry"]
        assert voice.deadline > time.monotonic()
        assert "Didn't catch speech" in capsys.readouterr().out
        await voice.close()

    asyncio.run(run())


def test_unrelated_422_is_not_hidden_as_empty_speech(capsys):
    async def run():
        def handler(request):
            if request.url.path == "/assistant":
                return httpx.Response(200, json={"session_id": "personal"})
            return httpx.Response(422, json={"detail": "A valid PCM WAV recording is required."})

        voice = session(handler)
        await voice.turn(b"bad")
        assert "valid PCM WAV" in capsys.readouterr().out
        await voice.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("state", "plays_reply"), [("playing", False), ("paused", True), ("unknown", True), (None, True)]
)
@pytest.mark.parametrize("half_duplex", [False, True])
def test_only_verified_music_playback_suppresses_spoken_reply(state, plays_reply, half_duplex):
    async def run():
        def handler(request):
            if request.url.path == "/assistant":
                return httpx.Response(200, json={"session_id": "personal"})
            if request.url.path == "/assistant/voice":
                return httpx.Response(200, json={"id": "voice", "transcript": "play music"})
            if request.url.path == "/chat":
                events = [
                    {"type": "turn_phase", "turn_id": "turn"},
                    {"type": "tool_status", "status": "success", "media_playback": state},
                    {"type": "text", "content": "Playing the track."},
                ]
                return httpx.Response(200, text="\n".join(json.dumps(e) for e in events))
            raise AssertionError(request.url)

        voice = session(handler)
        voice.audio.half_duplex = half_duplex
        replies = []

        async def reply(turn):
            replies.append(turn)

        voice.reply_audio = reply
        await voice.turn(b"wav")
        assert bool(replies) == plays_reply
        assert voice._ended == (not plays_reply)
        assert voice.pause_requested == (half_duplex and not plays_reply)
        await asyncio.sleep(0)
        assert voice.audio.cues == (["followup"] if plays_reply else [])  # No earcon over music.
        await voice.close()

    asyncio.run(run())


def test_short_noise_during_playback_does_not_interrupt():
    async def run():
        voice = session()
        voice.audio.playing = True
        voice.task = asyncio.create_task(asyncio.sleep(100))
        for _ in range(3):
            await voice.feed(b"\x01\x10" * 1600)
        await voice.feed(bytes(3200))
        assert not voice.collecting and voice.audio.interruptions == 0
        voice.task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await voice.task
        await voice.close()

    asyncio.run(run())


def test_replacing_cue_keeps_capture_guard_until_new_cue_finishes():
    async def run():
        voice = session()
        entered, finish = asyncio.Event(), asyncio.Event()

        async def slow_cue(kind):
            entered.set()
            await finish.wait()

        voice.audio.cue = slow_cue
        voice.cue("wake")
        await entered.wait()
        old = voice._cue_task
        voice.cue("sleep")
        with contextlib.suppress(asyncio.CancelledError):
            await old
        assert voice._cue_active
        finish.set()
        await voice._cue_task
        assert not voice._cue_active
        await voice.close()

    asyncio.run(run())


def test_pause_returns_from_capture_loop_and_closes_devices(monkeypatch):
    from yumi.voice import client, conversation, duplex

    async def run():
        voice = session(lambda _: httpx.Response(200, json={"request_cancellation": True}))
        closed = []
        voice.audio.start = lambda: None
        voice.audio.close = lambda: closed.append(True)

        async def frame():
            await voice.standby(pause=True)
            return bytes(3200)

        voice.audio.read_frame = frame
        monkeypatch.setattr(duplex, "DuplexAudio", lambda *a: voice.audio)
        monkeypatch.setattr(conversation, "VoiceSession", lambda *a, **kw: voice)
        result = await client.run_client(VoiceConnection("https://example.test"), voice.wake, None)
        assert result == "paused"
        assert closed == [True]
        assert voice.http.is_closed

    asyncio.run(run())


def test_speech_during_wake_cue_is_preserved_for_transcription():
    async def run():
        voice = session()
        release = asyncio.Event()
        recordings = []

        async def cue(kind):
            await release.wait()

        async def turn(wav, previous=None):
            recordings.append(wav)

        voice.audio.cue = cue
        voice.turn = turn
        await voice.feed(bytes(3200))  # Wake
        # Say a short command while the cue is still playing.
        for _ in range(3):
            await voice.feed(b"\x01\x10" * 1600)
        release.set()
        await voice._cue_task
        for _ in range(8):
            await voice.feed(bytes(3200))
        await asyncio.sleep(0)
        assert len(recordings) == 1
        assert b"\x01\x10" * 4800 in recordings[0]
        await voice.close()

    asyncio.run(run())


def test_enter_wakes_without_keyword_but_never_confirms_an_action():
    async def run():
        voice = session()
        voice.request_wake()
        await voice.feed(bytes(3200))
        await asyncio.sleep(0)
        assert voice._awake and voice.wake.calls == 0
        assert voice.audio.cues == ["wake"]
        voice.confirmation = asyncio.get_running_loop().create_future()
        voice.request_wake()
        assert not voice._manual_wake
        assert not voice.confirmation.done()
        await voice.close()

    asyncio.run(run())


def test_input_level_notice_is_local_and_does_not_repeat(capsys):
    async def run():
        voice = session(lambda _: pytest.fail("Input levels must not leave the device"))
        voice._last_input_notice = time.monotonic() - 31
        for _ in range(200):
            voice.input_notice(bytes(3200))
        assert capsys.readouterr().out.count("Microphone signal is very quiet") == 1
        await voice.close()

    asyncio.run(run())


def test_half_duplex_reply_keeps_one_output_window_across_parts():
    async def run():
        windows = []
        voice = session()
        voice.audio.half_duplex = True

        @contextlib.asynccontextmanager
        async def output():
            windows.append("open")
            try:
                yield
            finally:
                windows.append("close")

        voice.audio.speech_output = output
        data = base64.b64encode(b"speech").decode()
        await voice.http.aclose()
        voice.http = httpx.AsyncClient(
            base_url="https://example.test",
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, text="\n".join(json.dumps({"type": "part", "index": i, "audio": data}) for i in range(2))
                )
            ),
        )
        await voice.reply_audio("turn")
        assert windows == ["open", "close"]
        assert voice.audio.played == [b"speech", b"speech"]
        assert not voice._output_active
        await voice.close()

    asyncio.run(run())


def test_enter_during_confirmation_stops_half_duplex_audio_without_approving():
    async def run():
        voice = session()
        voice._output_active = True
        voice.confirmation = asyncio.get_running_loop().create_future()
        voice.request_wake()
        assert voice.audio.interruptions == 1
        assert not voice.confirmation.done()
        assert not voice._manual_wake
        await voice.close()

    asyncio.run(run())


def test_enter_stops_half_duplex_reply_and_wakes_after_capture_restored():
    async def run():
        voice = session()
        voice.audio.half_duplex = True
        entered = asyncio.Event()
        restored = []

        @contextlib.asynccontextmanager
        async def output():
            try:
                yield
            finally:
                restored.append(True)

        voice.audio.speech_output = output

        async def reply():
            async with voice.spoken_output():
                entered.set()
                await asyncio.Event().wait()

        voice.task = asyncio.create_task(reply())
        await entered.wait()
        voice.request_wake()
        with pytest.raises(asyncio.CancelledError):
            await voice.task
        assert restored and not voice._output_active
        assert voice._manual_wake
        await voice.feed(bytes(3200))
        await asyncio.sleep(0)
        assert voice._awake and voice.audio.cues == ["wake"]
        await voice.close()

    asyncio.run(run())


@pytest.mark.parametrize("half_duplex", [False, True])
def test_terminal_success_closes_microphone_before_stream_ends_without_tts(half_duplex):
    async def run():
        released = asyncio.Event()
        paths = []

        class ChatStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'{"type":"turn_phase","turn_id":"turn","phase":"model"}\n'
                # A stale paused snapshot must not override explicit completion.
                yield b'{"type":"tool_status","status":"success","media_playback":"paused","content":"done"}\n'
                yield b'{"type":"text","content":"Starting the track"}\n'
                yield b'{"type":"turn_complete","turn_id":"turn","reply":"none","reason":"tool_success","voice_capture":"pause"}\n'
                assert released.is_set(), "do not keep the microphone open while draining the stream"
                await asyncio.sleep(0)
                yield b'{"type":"turn_timing","turn_id":"turn","duration_ms":10}\n'

        def handler(request):
            paths.append(request.url.path)
            if request.url.path == "/chat/capabilities":
                return httpx.Response(200, json={"request_cancellation": True, "silent_tool_completion": True})
            if request.url.path == "/assistant":
                return httpx.Response(200, json={"session_id": "personal"})
            if request.url.path == "/assistant/voice":
                return httpx.Response(200, json={"id": "voice", "transcript": "play music"})
            if request.url.path == "/chat":
                return httpx.Response(200, stream=ChatStream())
            raise AssertionError(f"Unexpected request: {request.url.path}")

        voice = session(handler)
        voice.audio.half_duplex = half_duplex
        voice.audio.close = released.set

        def start():
            voice.task = asyncio.create_task(voice.turn(b"wav"))

        async def read():
            await released.wait()
            raise RuntimeError("Audio device closed")

        voice.audio.start, voice.audio.read_frame = start, read
        assert await asyncio.wait_for(voice.run(), timeout=2) == "paused"
        assert released.is_set() and voice.pause_requested
        assert not voice.audio.played
        assert "/chat/cancel" not in paths
        assert "followup" not in voice.audio.cues
        await voice.close()

    asyncio.run(run())


def test_streaming_tts_error_without_buffered_body_still_reports_failure(capsys):
    async def run():
        class ErrorStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'{"detail":"reply not ready"}'

        def handler(request):
            if request.url.path == "/assistant":
                return httpx.Response(200, json={"session_id": "personal"})
            if request.url.path == "/assistant/voice":
                return httpx.Response(200, json={"id": "voice", "transcript": "hello"})
            if request.url.path == "/chat":
                return httpx.Response(
                    200, text='{"type":"turn_phase","turn_id":"turn"}\n{"type":"text","content":"Hi"}\n'
                )
            if request.url.path == "/assistant/voice/reply/stream":
                return httpx.Response(409, stream=ErrorStream())
            if request.url.path == "/chat/cancel":
                return httpx.Response(200, json={"status": "cancelled"})
            raise AssertionError(request.url)

        voice = session(handler)
        await voice.turn(b"wav")
        await asyncio.sleep(0)
        assert "Voice turn failed (409)" in capsys.readouterr().out
        assert voice.audio.cues == ["retry"]
        await voice.close()

    asyncio.run(run())


def test_default_endpoint_keeps_thinking_pause_in_one_recording():
    async def run():
        voice = VoiceSession(
            VoiceConnection("https://test"),
            Audio(),
            Wake(),
            vad=SimpleNamespace(is_speech=lambda frame, _: frame[0] != 0),
        )
        recordings = []

        async def turn(wav, previous=None):
            recordings.append(wav)

        voice.turn = turn
        voice.activate()
        await voice._cue_task
        speech, silence = b"\x01\x10" * 1600, bytes(3200)
        for frame in [speech] * 4 + [silence] * 20 + [speech] * 4 + [silence] * 24:
            await voice.feed(frame)
        assert voice.collecting and not recordings
        await voice.feed(silence)
        await voice.task
        assert len(recordings) == 1
        assert voice.collector.max_ms == 60000
        await voice.close()

    asyncio.run(run())


def test_resuming_during_stt_combines_audio_without_sending_partial_chat():
    async def run():
        chats, recordings = [], []
        entered = asyncio.Event()

        def handler(request):
            if request.url.path == "/assistant":
                return httpx.Response(200, json={"session_id": "personal"})
            if request.url.path == "/chat":
                chats.append(json.loads(request.content))
                return httpx.Response(200, text='{"type":"turn_phase","turn_id":"turn"}\n')
            pytest.fail(f"Unexpected request {request.url}")

        voice = session(handler)

        async def transcribe(wav, session_id):
            recordings.append(wav)
            if len(recordings) == 1:
                entered.set()
                await asyncio.Event().wait()
            return {"id": "combined", "transcript": "完整的一句话"}

        voice.transcribe = transcribe
        voice.activate()
        await voice._cue_task
        first, second, silence = b"\x01\x10" * 1600, b"\x02\x10" * 1600, bytes(3200)
        for frame in [first] * 4 + [silence] * 8:
            await voice.feed(frame)
        await entered.wait()
        await voice._cue_task
        for frame in [second] * 4 + [silence] * 8:
            await voice.feed(frame)
        await voice.task
        assert len(recordings) == 2
        assert first in recordings[-1] and second in recordings[-1]
        assert len(chats) == 1 and chats[0]["voice_id"] == "combined"
        assert not voice._pending_pcm
        await voice.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("我记得，嗯嗯…", True),
        ("让我想想。", True),
        ("えっと…", True),
        ("Let me think.", True),
        ("嗯，我要听这首歌", False),
        ("确认", False),
    ],
)
def test_only_explicit_hesitation_gets_extra_time(text, expected):
    from yumi.voice.conversation import needs_thinking_time

    assert needs_thinking_time(text) == expected


def test_media_end_recreates_audio_and_resumes_awake(monkeypatch):
    from yumi.voice import client, conversation, duplex, media_wait

    async def run():
        sessions, devices = [], []

        class Device(Audio):
            def __init__(self, *args):
                super().__init__()
                self.closed = False
                devices.append(self)

            def close(self):
                self.closed = True

        class Session:
            def __init__(self, connection, audio, wake, **kwargs):
                self.audio = audio
                self.http = object()
                self.media_watch = "turn" if not sessions else None
                self.start_awake = False
                sessions.append(self)

            async def run(self):
                assert not self.audio.closed
                return "paused"

            async def close(self):
                self.audio.close()

        async def wait(http, turn):
            assert devices[0].closed and len(devices) == 1
            return True

        monkeypatch.setattr(duplex, "DuplexAudio", Device)
        monkeypatch.setattr(conversation, "VoiceSession", Session)
        monkeypatch.setattr(media_wait, "wait_for_media", wait)
        assert await client.run_client(VoiceConnection("https://test"), Wake(), None) == "paused"
        assert len(sessions) == 2
        assert not sessions[0].start_awake and sessions[1].start_awake
        assert all(d.closed for d in devices)

    asyncio.run(run())


@pytest.mark.parametrize("outcome", ["success", "play_failed", "profile_failed", "cancel", "ack_failed"])
def test_media_readiness_precedes_playback_and_restores_capture_on_failure(outcome):
    async def run():
        actions = []
        held = False
        closed = False
        preparation_id = "a" * 32

        class ChatStream(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'{"type":"turn_phase","turn_id":"turn","phase":"model"}\n'
                yield (
                    json.dumps({"type": "media_prepare", "turn_id": "turn", "preparation_id": preparation_id}) + "\n"
                ).encode()
                assert "ready" in actions or "not ready" in actions
                if outcome == "profile_failed":
                    yield b'{"type":"error","content":"Speaker not ready"}\n'
                elif outcome == "play_failed":
                    actions.append("play failed")
                    yield b'{"type":"tool_status","status":"error","content":"Player unavailable"}\n'
                    yield b'{"type":"text","content":"Could not start the track"}\n'
                else:
                    assert held and "ready" in actions and not closed
                    actions.append("play")
                    yield b'{"type":"turn_complete","turn_id":"turn","reply":"none","reason":"tool_success","voice_capture":"pause"}\n'
                    assert closed  # Held capture is never reopened on success.

        def handler(request):
            path = request.url.path
            if path == "/assistant":
                return httpx.Response(200, json={"session_id": "personal"})
            if path == "/assistant/voice":
                return httpx.Response(200, json={"id": "voice", "transcript": "play music"})
            if path == "/chat":
                assert json.loads(request.content)["prepare_media_output"] is True
                return httpx.Response(200, stream=ChatStream())
            if path == "/assistant/voice/media-ready":
                body = json.loads(request.content)
                assert body["preparation_id"] == preparation_id
                if body["ready"]:
                    assert held and "profile ready" in actions
                    actions.append("ready")
                else:
                    assert not held
                    actions.append("not ready")
                return httpx.Response(503 if outcome == "ack_failed" else 200, json={"ok": True})
            if path == "/chat/cancel":
                actions.append("cancel server")
                return httpx.Response(200, json={"status": "cancelled"})
            raise AssertionError(path)

        voice = session(handler)
        voice._media_prepare_supported = True
        voice.audio.can_prepare_media = True
        voice.audio.half_duplex = True

        def close():
            nonlocal closed
            closed = True
            actions.append("close")

        voice.audio.close = close
        entered = asyncio.Event()

        @contextlib.asynccontextmanager
        async def media():
            nonlocal held
            held = True
            actions.append("release capture")
            entered.set()
            try:
                if outcome == "cancel":
                    await asyncio.Event().wait()
                if outcome == "profile_failed":
                    raise RuntimeError("still in call mode")
                actions.append("profile ready")
                yield
            finally:
                held = False
                if not closed:
                    actions.append("restore capture")

        voice.audio.media_output = media

        async def reply(turn):
            assert not held and "restore capture" in actions
            actions.append("reply")

        voice.reply_audio = reply
        voice.task = asyncio.create_task(voice.turn(b"wav"))
        if outcome == "cancel":
            await entered.wait()
            voice.request_wake()  # Enter cancels preparation and the server request.
            with pytest.raises(asyncio.CancelledError):
                await voice.task
        else:
            await voice.task
        assert not held and not voice._output_active
        if outcome == "success":
            assert actions.index("profile ready") < actions.index("ready") < actions.index("play")
            assert "restore capture" not in actions and voice.pause_requested
        else:
            assert "restore capture" in actions and not voice.pause_requested and "play" not in actions
        if outcome == "play_failed":
            assert "reply" in actions
        await voice.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "phrase",
    [
        "Finish. See you later.",
        "I'm heading out now; let's leave our chat here for the moment.",
        "See you later",
        "Thanks, talk to you later.",
        "Goodbye, Yumi.",
        "おやすみなさい。",
        "またね",
        "回见",
    ],
)
def test_farewells_enter_standby_without_chat_or_tts(phrase):
    async def run():
        paths = []

        def handler(request):
            paths.append(request.url.path)
            if request.url.path == "/assistant":
                return httpx.Response(200, json={"session_id": "personal"})
            if request.url.path == "/assistant/voice":
                return httpx.Response(200, json={"id": "voice", "transcript": phrase})
            raise AssertionError(request.url.path)

        voice = session(handler)
        await voice.turn(b"wav")
        assert voice._ended and not voice.pause_requested and voice.deadline == 0
        assert voice.audio.cues == ["sleep"]
        assert paths == ["/assistant", "/assistant/voice"]
        await voice.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "phrase",
    [
        "Play See You Later",
        "How do I say goodbye in Japanese?",
        "Do not stop listening",
        '"Goodbye"',
        "Turn off the lights, then good night",
        "Finish the song and keep listening",
    ],
)
def test_farewell_mentions_do_not_end_voice(phrase):
    from yumi.voice.conversation import conversation_control

    assert conversation_control(phrase) is None


def test_verified_voice_standby_tool_keeps_wake_enabled_and_skips_tts():
    async def run():
        def handler(request):
            if request.url.path == "/assistant":
                return httpx.Response(200, json={"session_id": "personal"})
            if request.url.path == "/assistant/voice":
                return httpx.Response(
                    200, json={"id": "voice", "transcript": "I'm heading out; let's leave our chat here for now"}
                )
            if request.url.path == "/chat":
                assert json.loads(request.content)["voice_session_controls"] is True
                return httpx.Response(
                    200,
                    text='{"type":"turn_phase","turn_id":"turn"}\n{"type":"text","content":"See you"}\n{"type":"voice_standby","turn_id":"turn"}\n',
                )
            raise AssertionError(request.url.path)

        voice = session(handler)
        voice._voice_controls_supported = True
        closed = []
        voice.audio.close = lambda: closed.append(True)
        await voice.turn(b"wav")
        assert voice._ended and not voice.pause_requested and not closed
        assert voice.audio.cues == ["sleep"]
        assert not voice.audio.played
        voice.activate()
        assert voice._awake and not voice._ended
        await voice.close()

    asyncio.run(run())
