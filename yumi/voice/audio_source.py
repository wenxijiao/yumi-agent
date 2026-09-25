"""Audio source abstraction.

The voice loop pulls fixed-size 16-bit PCM frames from an :class:`AudioSource`.
Production runs use :class:`SoundDeviceSource` (a thin wrapper over
``sounddevice.RawInputStream``); tests inject a :class:`FakeAudioSource` so the
loop can be exercised without a real microphone.

Frames are 16 kHz, mono, signed 16-bit little-endian PCM. The frame length
(in samples) is fixed at construction so the wake detector's expected block
size lines up with what we read from the mic.
"""

from __future__ import annotations

import queue
import threading
from typing import Protocol


class AudioSource(Protocol):
    """A pull-based source of mono 16-bit PCM frames at 16 kHz."""

    sample_rate: int
    frame_length: int  # samples per frame (frame is 2*frame_length bytes)

    def start(self) -> None: ...

    def read_frame(self) -> bytes:
        """Block until one PCM frame (``2 * frame_length`` bytes) is available."""
        ...

    def stop(self) -> None: ...


class SoundDeviceSource:
    """Real microphone capture via the ``sounddevice`` library.

    ``sounddevice`` ships with yumi-agent; importing this class without it
    raises a clear repair hint for broken/partial installs.
    """

    def __init__(self, *, sample_rate: int, frame_length: int, device: int | None = None) -> None:
        try:
            import sounddevice as sd  # noqa: F401
        except ImportError as exc:  # pragma: no cover - import-time guard
            raise RuntimeError(
                "sounddevice is not importable. Reinstall with: pip install --force-reinstall yumi-agent"
            ) from exc
        self.sample_rate = int(sample_rate)
        self.frame_length = int(frame_length)
        self.device = device
        self._stream = None
        self._frames: queue.Queue[bytes] = queue.Queue(maxsize=16)
        self._stopped = threading.Event()

    def start(self) -> None:
        import sounddevice as sd

        self._frames = queue.Queue(maxsize=16)
        self._stopped.clear()

        def capture(indata, frames, _time_info, _status):
            if self._stopped.is_set():
                return
            data = bytes(indata)
            if frames != self.frame_length or len(data) != self.frame_length * 2:
                return
            try:
                self._frames.put_nowait(data)
            except queue.Full:
                # Keep the freshest microphone frame if processing lags.
                try:
                    self._frames.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._frames.put_nowait(data)
                except queue.Full:
                    pass

        self._stream = sd.RawInputStream(
            samplerate=self.sample_rate,
            blocksize=self.frame_length,
            dtype="int16",
            channels=1,
            device=self.device,
            callback=capture,
        )
        self._stream.start()

    def read_frame(self) -> bytes:
        if self._stopped.is_set():
            return b"\0\0" * self.frame_length
        if self._stream is None:
            raise RuntimeError("AudioSource not started")
        while not self._stopped.is_set():
            try:
                return self._frames.get(timeout=0.2)
            except queue.Empty:
                continue
        # A server shutdown signals stop while read_frame runs in an executor.
        # Returning silence lets the voice loop observe its stop event.
        return b"\0\0" * self.frame_length

    def stop(self) -> None:
        self._stopped.set()
        if self._stream is not None:
            try:
                # Abort drops buffered input, including the spoken reply.
                self._stream.abort()
            finally:
                self._stream.close()
                self._stream = None


class FakeAudioSource:
    """Test double that replays a pre-built sequence of frames.

    When the queue is exhausted, returns silence forever so tests can probe
    the loop without managing termination signals manually.
    """

    def __init__(self, frames: list[bytes], *, sample_rate: int = 16000, frame_length: int = 512) -> None:
        self.sample_rate = sample_rate
        self.frame_length = frame_length
        self._frames = list(frames)
        self._silence = b"\x00\x00" * frame_length
        self._index = 0
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def read_frame(self) -> bytes:
        if self._index < len(self._frames):
            frame = self._frames[self._index]
            self._index += 1
            return frame
        return self._silence

    def stop(self) -> None:
        self.stopped = True
