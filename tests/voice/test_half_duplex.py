from __future__ import annotations

import asyncio
from types import SimpleNamespace

import numpy as np
import pytest
from yumi.voice.coreaudio import OutputFormat
from yumi.voice.half_duplex import HalfDuplexAudio


@pytest.fixture
def audio(monkeypatch):
    events = []

    class Capture:
        playing = False

        def __init__(self, *args):
            self.closed = False
            self.event = asyncio.Event()
            events.append("capture opened")

        def start(self):
            events.append("capture started")

        def interrupt(self):
            pass

        def close(self):
            self.closed = True
            self.event.set()
            events.append("capture closed")

        async def read_frame(self):
            await self.event.wait()
            raise RuntimeError("Audio device closed")

    monkeypatch.setattr("yumi.voice.half_duplex.DuplexAudio", Capture)
    devices = [
        dict(name="mic", hostapi=0, default_samplerate=48000, max_input_channels=1, max_output_channels=0),
        dict(name="speaker", hostapi=0, default_samplerate=48000, max_input_channels=0, max_output_channels=2),
    ]
    monkeypatch.setattr(
        "yumi.voice.half_duplex.sd.query_devices",
        lambda *a: (devices[0] if a[1] == "input" else devices[1]) if len(a) > 1 else devices,
    )
    monkeypatch.setattr("yumi.voice.half_duplex.output_format", lambda _: None)
    real_sleep = asyncio.sleep

    async def quick_sleep(delay):
        await real_sleep(0)

    monkeypatch.setattr("yumi.voice.half_duplex.asyncio.sleep", quick_sleep)
    obj = HalfDuplexAudio()
    obj._open_output = lambda: events.append("output opened")
    obj._close_output = lambda: events.append("output closed")
    obj.start()
    yield obj, events
    obj.close()


def test_capture_released_once_for_whole_reply_and_reopened_afterward(audio):
    obj, events = audio

    async def run():
        async with obj.speech_output():
            assert obj.capture_suspended and obj._capture is None
            assert await obj.read_frame() is None
            async with obj.speech_output():
                pass  # A nested segment does not toggle Bluetooth profiles.
            assert events.count("capture closed") == 1
        assert not obj.capture_suspended and obj._capture is not None
        assert events.count("capture opened") == 2
        assert events.index("capture closed") < events.index("output opened")
        assert events.index("output closed") < len(events) - 2

    asyncio.run(run())


def test_cancelled_playback_still_restores_capture(audio):
    obj, events = audio

    async def run():
        entered = asyncio.Event()

        async def playback():
            async with obj.speech_output():
                entered.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(playback())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not obj.capture_suspended
        assert events.count("capture started") == 2

    asyncio.run(run())


def test_output_open_failure_restores_capture(audio):
    obj, events = audio

    def fail():
        raise RuntimeError("speaker missing")

    obj._open_output = fail

    async def run():
        with pytest.raises(RuntimeError, match="speaker missing"):
            async with obj.speech_output():
                pytest.fail("must not play")
        assert not obj.capture_suspended
        assert events.count("capture started") == 2

    asyncio.run(run())


def test_reader_does_not_treat_deliberate_release_as_device_failure(audio):
    obj, _ = audio

    async def run():
        reader = asyncio.create_task(obj.read_frame())
        await asyncio.sleep(0)
        async with obj.speech_output():
            assert await reader is None

    asyncio.run(run())


def test_bluetooth_waits_for_native_format_before_opening_output(audio, monkeypatch):
    obj, events = audio
    obj._bluetooth = True
    formats = iter([OutputFormat(8000, True), OutputFormat(8000, True), OutputFormat(44100, True)])

    def native(_):
        assert obj._capture is None and "output opened" not in events
        events.append("native format polled")
        return next(formats)

    monkeypatch.setattr("yumi.voice.half_duplex.output_format", native)

    async def run():
        async with obj.speech_output():
            assert obj._native_rate == 44100
        assert events.count("native format polled") == 3

    asyncio.run(run())


def test_profile_wait_is_bounded_and_does_not_claim_high_quality(audio, monkeypatch, capsys):
    obj, _ = audio
    obj._bluetooth = True
    monkeypatch.setattr("yumi.voice.half_duplex.output_format", lambda _: OutputFormat(8000, True))

    async def run():
        async with obj.speech_output():
            assert obj._native_rate is None

    asyncio.run(run())
    assert "quality could not be verified" in capsys.readouterr().out


def test_closed_client_does_not_reopen_microphone_during_restore(audio):
    obj, events = audio

    async def run():
        async with obj.speech_output():
            obj.close()
        assert events.count("capture opened") == 1
        assert obj._capture is None

    asyncio.run(run())


def test_resume_failure_reaches_capture_loop(audio, monkeypatch):
    obj, _ = audio

    def fail(*a):
        raise RuntimeError("device removed")

    monkeypatch.setattr("yumi.voice.half_duplex.DuplexAudio", fail)

    async def run():
        with pytest.raises(RuntimeError, match="device removed"):
            async with obj.speech_output():
                pass
        with pytest.raises(RuntimeError, match="Microphone could not be reopened"):
            await obj.read_frame()

    asyncio.run(run())


def test_output_callback_preserves_pcm_and_drains_after_last_block(audio):
    obj, _ = audio
    obj._output_channels = 2
    obj._pending_pcm = np.array([100, -200, 32767], dtype=np.int16).tobytes()
    block = bytearray(8)
    status = SimpleNamespace(output_underflow=False)
    obj._output_callback(block, 2, None, status)
    assert np.frombuffer(block, dtype=np.int16).tolist() == [100, 100, -200, -200]
    assert not obj._drained
    obj._output_callback(block, 2, None, status)
    assert np.frombuffer(block, dtype=np.int16).tolist() == [32767, 32767, 0, 0]
    assert not obj._drained
    obj._output_callback(block, 2, None, status)
    assert obj._drained and block == bytes(8)


def test_device_resolution_follows_names_and_fails_closed_on_ambiguity(audio, monkeypatch):
    obj, _ = audio
    devices = [dict(name="speaker", hostapi=0, max_output_channels=2)]
    monkeypatch.setattr("yumi.voice.half_duplex.sd.query_devices", lambda: devices)
    assert obj._resolve_device("speaker", 0, "output") == 0
    devices.append(devices[0].copy())
    with pytest.raises(RuntimeError, match="ambiguous"):
        obj._resolve_device("speaker", 0, "output")


@pytest.mark.parametrize("complete", [True, False])
def test_media_preparation_holds_both_streams_closed_until_success_or_failure(audio, monkeypatch, complete):
    obj, events = audio
    obj._bluetooth = True
    rates = iter([8000, 44100, 8000, 44100, 44100])
    monkeypatch.setattr("yumi.voice.half_duplex.output_format", lambda _: OutputFormat(next(rates), True))

    async def run():
        async with obj.media_output():
            assert obj._native_rate == 44100 and obj.capture_suspended
            assert obj._capture is None and "output opened" not in events
            assert list(rates) == []  # Require consecutive ready samples after a transient.
            if complete:
                obj.close()  # The terminal-success path must not reopen the input.
        assert events.count("capture opened") == (1 if complete else 2)
        assert "output opened" not in events

    asyncio.run(run())


def test_media_preparation_refuses_unverified_route_and_restores_microphone(audio, monkeypatch):
    obj, events = audio
    obj._bluetooth = True
    monkeypatch.setattr("yumi.voice.half_duplex.output_format", lambda _: OutputFormat(8000, True))

    async def run():
        with pytest.raises(RuntimeError, match="still in call mode"):
            async with obj.media_output():
                pytest.fail("must not start music")
        assert obj._capture is not None and not obj.capture_suspended
        assert events.count("capture started") == 2

    asyncio.run(run())


def test_cancelled_media_preparation_reopens_microphone(audio, monkeypatch):
    obj, events = audio
    entered = asyncio.Event()

    async def wait(**kwargs):
        entered.set()
        await asyncio.Event().wait()

    obj._wait_for_output_profile = wait

    async def run():
        async def prepare():
            async with obj.media_output():
                pytest.fail("must not start music")

        task = asyncio.create_task(prepare())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert obj._capture is not None and not obj.capture_suspended
        assert events.count("capture started") == 2

    asyncio.run(run())
