"""Release the input device for the entire spoken reply, then reopen capture.

This gives the OS a chance to leave Bluetooth HFP. A high sample rate alone is
not proof of an A2DP route; other applications holding the mic can prevent it.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from contextlib import asynccontextmanager

import numpy as np
import sounddevice as sd

from yumi.voice.coreaudio import output_format
from yumi.voice.duplex import DuplexAudio


class HalfDuplexAudio:
    half_duplex = True

    def __init__(self, input_device=None, output_device=None):
        mic = sd.query_devices(input_device, "input")
        speaker = sd.query_devices(output_device, "output")
        self._mic_name, self._mic_hostapi = mic["name"], mic["hostapi"]
        self._speaker_name, self._speaker_hostapi = speaker["name"], speaker["hostapi"]
        native = output_format(self._speaker_name)
        self._bluetooth = self._mic_name == self._speaker_name and (
            native.bluetooth if native else mic["default_samplerate"] <= 16000
        )
        # Opt in only where the native route can actually be verified. Other
        # devices/platforms retain their existing playback behavior.
        self.can_prepare_media = self._bluetooth and native is not None
        self._native_rate = None
        self._capture = DuplexAudio(input_device, output_device)
        self.capture_suspended = False
        self._output = None
        self._closed = False
        self._started = False
        self._depth = 0
        self.cue_volume = 70
        self._lock = threading.Lock()
        self._pending_pcm = b""
        self._pcm_offset = 0
        self._play_generation = 0
        self._playback_error = None
        self._drained = False
        self._output_rate = 48000
        self._output_channels = 1
        self._resume_error = None

    @property
    def playing(self):
        return (self._output is not None and not self._drained) or bool(self._capture and self._capture.playing)

    def start(self):
        self._capture.start()
        self._started = True

    async def read_frame(self):
        if self._closed:
            raise RuntimeError("Audio device closed")
        if self._resume_error:
            raise RuntimeError(
                "Microphone could not be reopened. Reconnect the device and restart --voice."
            ) from self._resume_error
        capture = self._capture
        if self.capture_suspended or capture is None:
            await asyncio.sleep(0.05)
            return None
        try:
            return await capture.read_frame()
        except RuntimeError:
            # The reply can release capture while read_frame is awaiting input.
            if self.capture_suspended or capture is not self._capture:
                return None
            raise

    def interrupt(self):
        self._play_generation += 1
        with self._lock:
            self._pending_pcm = b""
            self._pcm_offset = 0
            self._drained = True
        if self._capture:
            self._capture.interrupt()

    def _output_callback(self, outdata, frames, timing, status):
        if status.output_underflow:
            self._playback_error = RuntimeError("Audio output underrun; try another output device.")
        size = frames * 2
        with self._lock:
            pcm = self._pending_pcm[self._pcm_offset : self._pcm_offset + size]
            self._pcm_offset += len(pcm)
            # Mark drained on the next callback so the final block reaches the device.
            self._drained = not pcm
        mono = np.frombuffer(pcm.ljust(size, b"\0"), dtype=np.int16)
        outdata[:] = np.repeat(mono[:, None], self._output_channels, axis=1).tobytes()

    @staticmethod
    def _resolve_device(name, hostapi, direction):
        # Profile transitions can reorder device indices. Keep the user's choice.
        matches = [
            i
            for i, d in enumerate(sd.query_devices())
            if d["name"] == name and d["hostapi"] == hostapi and d[f"max_{direction}_channels"] > 0
        ]
        if len(matches) != 1:
            raise RuntimeError(
                f"Selected {direction} device is unavailable or ambiguous. Reconnect it and restart --voice."
            )
        return matches[0]

    async def _wait_for_output_profile(self, *, stable_samples=1):
        self._native_rate = None
        if not self._bluetooth:
            return
        # Opening output too early can keep macOS stuck in HFP. Wait with BOTH
        # streams closed; a 48 kHz application stream alone proves nothing.
        stable = 0
        for _ in range(20):
            native = output_format(self._speaker_name)
            if native and native.rate >= 32000:
                stable += 1
                if stable >= stable_samples:
                    self._native_rate = int(native.rate)
                    print(f"Speaker playback format: {self._native_rate} Hz", flush=True)
                    return
            else:
                stable = 0
            await asyncio.sleep(0.2)
        print(
            "Bluetooth playback quality could not be verified. Close Sound settings and other apps using "
            "the microphone if call quality persists; a separate microphone avoids profile switching.",
            flush=True,
        )

    def _open_output(self):
        device = self._resolve_device(self._speaker_name, self._speaker_hostapi, "output")
        info = sd.query_devices(device, "output")
        last_error = None
        rates = ([self._native_rate] if self._native_rate else []) + [48000, 44100, int(info["default_samplerate"])]
        for rate in dict.fromkeys(rates):
            for channels in dict.fromkeys([min(2, info["max_output_channels"]), 1]):
                stream = None
                try:
                    sd.check_output_settings(device=device, channels=channels, dtype="int16", samplerate=rate)
                    self._output_rate, self._output_channels = rate, channels
                    stream = sd.RawOutputStream(
                        device=device,
                        samplerate=rate,
                        channels=channels,
                        dtype="int16",
                        blocksize=rate // 100,
                        callback=self._output_callback,
                    )
                    stream.start()
                    self._output = stream
                    return
                except (sd.PortAudioError, ValueError) as exc:
                    last_error = exc
                    if stream is not None:
                        with contextlib.suppress(Exception):
                            stream.close()
        raise RuntimeError("Could not open output-only audio. Check the selected speaker.") from last_error

    def _close_output(self):
        stream, self._output = self._output, None
        if stream is not None:
            try:
                stream.abort()
            finally:
                stream.close()

    async def _restore_capture(self):
        try:
            try:
                self._close_output()
            finally:
                if not self._closed:
                    # A Bluetooth device may need an interval before accepting input.
                    await asyncio.sleep(0.25)
                    if not self._closed:
                        mic = self._resolve_device(self._mic_name, self._mic_hostapi, "input")
                        speaker = self._resolve_device(self._speaker_name, self._speaker_hostapi, "output")
                        self._capture = DuplexAudio(mic, speaker)
            if self._closed:
                return
            self._capture.cue_volume = self.cue_volume
            if self._started:
                self._capture.start()
        except Exception as exc:
            if self._capture:
                self._capture.close()
                self._capture = None
            self._resume_error = exc
            raise
        finally:
            self.capture_suspended = False

    @asynccontextmanager
    async def _released_capture(self):
        if self._depth:
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
            return
        self._depth = 1
        self.capture_suspended = True
        self.interrupt()
        capture, self._capture = self._capture, None
        try:
            if capture:
                capture.close()  # Closing, not just muting, releases Bluetooth input.
            yield
        finally:
            self._depth = 0
            self.interrupt()
            restore = asyncio.create_task(self._restore_capture())
            try:
                await asyncio.shield(restore)
            except asyncio.CancelledError:
                await restore
                raise

    @asynccontextmanager
    async def speech_output(self):
        async with self._released_capture():
            if self._output is None:
                print("▶ Playing reply with microphone released. Press Enter to interrupt.", flush=True)
                await self._wait_for_output_profile()
                self._open_output()
            yield

    @asynccontextmanager
    async def media_output(self):
        """Hold both streams closed until the external player finishes starting."""
        async with self._released_capture():
            print("♫ Preparing speaker for music… Press Enter to cancel.", flush=True)
            await self._wait_for_output_profile(stable_samples=2)
            if self._native_rate is None:
                raise RuntimeError("Bluetooth speaker is still in call mode; music was not started.")
            yield

    async def play(self, data):
        from yumi.voice.duplex import decode_audio

        if not self.capture_suspended:
            async with self.speech_output():
                await self.play(data)
            return
        if self._output is None:
            raise RuntimeError("Output-only stream is not ready")
        generation = self._play_generation
        pcm = await asyncio.to_thread(decode_audio, data, self._output_rate)
        if generation != self._play_generation:
            return
        with self._lock:
            self._pcm_offset = 0
            self._pending_pcm = pcm
            self._drained = False
            self._playback_error = None
        while not self._drained and generation == self._play_generation:
            if self._playback_error:
                raise self._playback_error
            if not self._output.active:
                raise RuntimeError("Speaker disconnected during playback")
            await asyncio.sleep(0.01)
        # Respect the output device's buffered latency before the next segment or close.
        if generation == self._play_generation:
            await asyncio.sleep(min(0.5, max(0.02, float(self._output.latency))))

    async def cue(self, kind):
        if self._capture and not self.capture_suspended:
            self._capture.cue_volume = self.cue_volume
            try:
                await self._capture.cue(kind)
            except RuntimeError:
                if not self.capture_suspended:
                    raise

    def close(self):
        self._closed = True
        self.interrupt()
        self._close_output()
        if self._capture:
            self._capture.close()
            self._capture = None
