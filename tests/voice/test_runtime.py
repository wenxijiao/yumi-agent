"""End-to-end test of the voice loop using fake mic + fake wake + fake VAD."""

from __future__ import annotations

import asyncio
import io
import wave

from kumi.voice.audio_source import FakeAudioSource
from kumi.voice.runtime import pcm_to_wav_bytes, run_voice_session
from kumi.voice.segmenter import FakeVad, UtteranceCollector
from kumi.voice.wake import FakeWake


def _speech_frame(frame_length: int) -> bytes:
    return b"\x80\x00" * frame_length  # first byte != 0 → FakeVad calls it speech


def _silence_frame(frame_length: int) -> bytes:
    return b"\x00\x00" * frame_length


def test_run_voice_session_dispatches_after_wake_and_silence():
    sample_rate = 16000
    frame_length = 512  # 32 ms
    speech = _speech_frame(frame_length)
    silence = _silence_frame(frame_length)

    # 1 frame: wake-word triggers
    # 5 frames of speech (~160 ms)
    # 30 frames of silence (~960 ms) — exceeds default 800 ms silence threshold
    frames = [silence] + [speech] * 5 + [silence] * 30

    source = FakeAudioSource(frames, sample_rate=sample_rate, frame_length=frame_length)
    wake = FakeWake(sample_rate=sample_rate, frame_length=frame_length, trigger_at=0)
    vad = FakeVad()
    collector = UtteranceCollector(
        sample_rate=sample_rate,
        frame_length=frame_length,
        silence_ms=800,
        max_ms=15000,
    )

    transcribed: list[bytes] = []
    dispatched: list[str] = []

    async def fake_transcribe(wav: bytes) -> str:
        transcribed.append(wav)
        return "what's the weather"

    async def fake_dispatch(text: str) -> None:
        dispatched.append(text)
        # Stop the loop after the first successful dispatch.
        stop_event.set()

    stop_event = asyncio.Event()

    async def runner() -> None:
        # Safety: cancel the loop if it hasn't stopped on its own within 2s.
        async def _watchdog() -> None:
            await asyncio.sleep(2.0)
            stop_event.set()

        watchdog = asyncio.create_task(_watchdog())
        await run_voice_session(
            source=source,
            wake=wake,
            collector=collector,
            is_speech=vad.is_speech,
            transcribe=fake_transcribe,
            dispatch=fake_dispatch,
            stop_event=stop_event,
        )
        watchdog.cancel()

    asyncio.run(runner())

    assert source.started
    assert source.stopped
    assert wake.closed
    assert len(transcribed) == 1
    assert transcribed[0].startswith(b"RIFF")  # WAV header
    assert dispatched == ["what's the weather"]


def test_pcm_to_wav_bytes_roundtrip():
    pcm = b"\x10\x00" * 100
    wav = pcm_to_wav_bytes(pcm, sample_rate=16000)
    with wave.open(io.BytesIO(wav), "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 16000
        assert wf.readframes(wf.getnframes()) == pcm


def test_utterance_collector_max_duration_force_flush():
    frame_length = 160  # 10 ms at 16 kHz
    collector = UtteranceCollector(
        sample_rate=16000,
        frame_length=frame_length,
        silence_ms=10_000,  # high — relies on max_ms to flush
        max_ms=1000,  # minimum allowed by the constructor's floor
    )
    speech = b"\x80\x00" * frame_length
    out = None
    for _ in range(150):  # 150 * 10 ms = 1500 ms > max_ms
        out = collector.feed(speech, is_speech=True)
        if out is not None:
            break
    assert out is not None
    assert len(out) >= 50 * frame_length * 2  # at least 50 frames of PCM


def test_utterance_collector_silence_flush():
    frame_length = 160  # 10 ms
    collector = UtteranceCollector(
        sample_rate=16000,
        frame_length=frame_length,
        silence_ms=100,  # 10 silent frames trigger flush (constructor floor)
        max_ms=10_000,
    )
    speech = b"\x80\x00" * frame_length
    silence = b"\x00\x00" * frame_length
    assert collector.feed(speech, is_speech=True) is None
    assert collector.feed(speech, is_speech=True) is None
    # 9 silent frames = 90 ms, still under 100 ms threshold.
    for _ in range(9):
        assert collector.feed(silence, is_speech=False) is None
    # 10th silent frame (100 ms total trailing silence) → flush.
    out = collector.feed(silence, is_speech=False)
    assert out is not None
    assert len(out) == 12 * frame_length * 2  # 2 speech + 10 silence frames
