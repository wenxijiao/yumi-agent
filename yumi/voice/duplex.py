"""Full duplex device audio, WebRTC AEC3, and portable PyAV playback.

Only the PortAudio callback touches the echo canceller and capture resampler.
The far-end reference is exactly the PCM sent to the output device. Network
work never stops capture. All application audio is mono 16 kHz / 100 ms.
"""

from __future__ import annotations

import asyncio
import io
import queue
import threading
import time
from collections import deque

import av
import numpy as np
import sounddevice as sd
from pywebrtc_audio import AudioProcessor


def device_settings(input_device=None, output_device=None):
    mic = sd.query_devices(input_device, "input")
    speaker = sd.query_devices(output_device, "output")
    if mic["max_input_channels"] < 1 or speaker["max_output_channels"] < 1:
        raise RuntimeError("A microphone and speaker are required. Use --voice-list-devices.")
    narrowband = mic["name"] == speaker["name"] and int(mic["default_samplerate"]) <= 16000
    rates = dict.fromkeys(
        ([int(mic["default_samplerate"])] if narrowband else [48000, 44100])
        + [int(mic["default_samplerate"]), int(speaker["default_samplerate"]), 16000, 8000]
    )
    for rate in rates:
        # Mono voice output also works after Bluetooth switches to hands-free.
        for channels in dict.fromkeys([1, min(2, speaker["max_output_channels"])]):
            try:
                sd.check_input_settings(device=input_device, channels=1, dtype="int16", samplerate=rate)
                sd.check_output_settings(device=output_device, channels=channels, dtype="int16", samplerate=rate)
                return rate, channels, mic["name"], speaker["name"]
            except sd.PortAudioError:
                continue
    raise RuntimeError(
        "Microphone and speaker have no shared sample rate. Choose another device with --voice-input-device / --voice-output-device."
    )


def select_input_device(input_device=None, output_device=None):
    """Prefer one unambiguous independent built-in/USB mic; respect explicit choice.

    A low-rate input sharing the speaker's name is a hands-free hint, not a
    definitive Bluetooth transport identification.
    """
    if input_device is not None:
        return input_device
    mic = sd.query_devices(kind="input")
    speaker = sd.query_devices(output_device, "output")
    if mic["name"] != speaker["name"] or int(mic["default_samplerate"]) > 16000:
        return None
    alternatives = [
        index
        for index, device in enumerate(sd.query_devices())
        if device["max_input_channels"] > 0
        and device["name"] != speaker["name"]
        and device["default_samplerate"] >= 32000
        and any(word in device["name"].casefold() for word in ("built-in", "internal", "macbook", "usb", "内建"))
    ]
    if len(alternatives) == 1:
        selected = alternatives[0]
        print(
            f"Using independent microphone: {sd.query_devices(selected)['name']} (keeps Bluetooth output out of hands-free mode)."
        )
        return selected
    print(
        "Audio quality: the selected microphone appears to share a Bluetooth hands-free device with the speaker. "
        "Keeping it open can reduce ALL audio, including music, to call quality. "
        "Use a separate USB/built-in microphone with --voice-input-device. "
        "Say 'pause microphone' to release capture; press Enter to resume."
    )
    return None


def decode_audio(data: bytes, rate: int) -> bytes:
    """Decode WAV/MP3/Ogg with bundled FFmpeg libraries; no shell player."""
    with av.open(io.BytesIO(data)) as container:
        resampler = av.AudioResampler(format="s16", layout="mono", rate=rate)
        chunks = []
        for frame in container.decode(audio=0):
            for output in resampler.resample(frame):
                chunks.append(output.to_ndarray().tobytes())
        for output in resampler.resample(None):
            chunks.append(output.to_ndarray().tobytes())
        return b"".join(chunks)


class DuplexAudio:
    sample_rate = 16000
    frame_length = 1600

    def __init__(self, input_device=None, output_device=None):
        self.cue_volume = 70
        self.rate, self.channels, mic, speaker = device_settings(input_device, output_device)
        print(f"Microphone: {mic}\nSpeaker: {speaker} ({self.rate} Hz)")
        self.block = self.rate // 100
        self._ap = AudioProcessor(
            sample_rate=self.rate,
            num_channels=1,
            echo_cancellation=True,
            noise_suppression=True,
            high_pass_filter=True,
            auto_gain_control=False,
        )
        self._resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
        self._capture = bytearray()
        self._incoming = queue.Queue(maxsize=20)
        self._render = deque()
        self._lock = threading.Lock()
        self._generation = 0
        self._last_output = 0.0
        self._error = None
        self._closed = False
        self._stream = sd.RawStream(
            device=(input_device, output_device),
            samplerate=self.rate,
            blocksize=self.block,
            channels=(1, self.channels),
            dtype="int16",
            callback=self._callback,
        )

    @property
    def playing(self):
        return bool(self._render) or time.monotonic() - self._last_output < 0.2

    def _callback(self, indata, outdata, frames, timing, status):
        try:
            with self._lock:
                far = self._render.popleft() if self._render else bytes(frames * 2)
            reference = np.frombuffer(far, dtype=np.int16)
            outdata[:] = np.repeat(reference[:, None], self.channels, axis=1).tobytes()
            if np.any(reference):
                self._last_output = time.monotonic()
            near = np.frombuffer(indata, dtype=np.int16)
            clean = self._ap.process(near, reference)
            frame = av.AudioFrame.from_ndarray(clean.reshape(1, -1), format="s16", layout="mono")
            frame.sample_rate = self.rate
            for output in self._resampler.resample(frame):
                self._capture.extend(output.to_ndarray().tobytes())
            while len(self._capture) >= 3200:
                data = bytes(self._capture[:3200])
                del self._capture[:3200]
                if self._incoming.full():
                    self._incoming.get_nowait()
                self._incoming.put_nowait(data)
        except Exception as exc:
            outdata[:] = bytes(len(outdata))
            self._error = exc
            raise sd.CallbackAbort from exc

    def start(self):
        self._stream.start()

    async def read_frame(self):
        while not self._closed:
            if not getattr(self._stream, "active", True):
                raise RuntimeError("Audio device disconnected or stopped. Reconnect it and restart --voice.")
            if self._error:
                raise RuntimeError(f"Audio device failed: {self._error}") from self._error
            try:
                return self._incoming.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.01)
        raise RuntimeError("Audio device closed")

    def interrupt(self):
        with self._lock:
            self._generation += 1
            self._render.clear()

    async def play(self, data: bytes):
        generation = self._generation
        pcm = await asyncio.to_thread(decode_audio, data, self.rate)
        await self._play_pcm(pcm, generation)

    async def cue(self, kind: str):
        from yumi.voice.cues import cue_pcm

        await self._play_pcm(cue_pcm(kind, self.rate, self.cue_volume), self._generation)

    async def _play_pcm(self, pcm: bytes, generation: int):
        size = self.block * 2
        for offset in range(0, len(pcm), size):
            while len(self._render) >= 50 and generation == self._generation:
                if self._error:
                    raise RuntimeError(f"Audio device failed: {self._error}") from self._error
                await asyncio.sleep(0.01)
            with self._lock:
                if generation != self._generation or self._closed:
                    return
                self._render.append(pcm[offset : offset + size].ljust(size, b"\0"))
        while self.playing and generation == self._generation and not self._closed:
            if self._error:
                raise RuntimeError(f"Audio device failed: {self._error}") from self._error
            await asyncio.sleep(0.01)

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.interrupt()
        self._stream.abort()
        self._stream.close()
