"""Audio source abstraction.

The voice loop pulls fixed-size 16-bit PCM frames from an :class:`AudioSource`.
Production runs use :class:`SoundDeviceSource` (a thin wrapper over
``sounddevice.RawInputStream``); tests inject a :class:`FakeAudioSource` so the
loop can be exercised without a real microphone.

Frames are 16 kHz, mono, signed 16-bit little-endian PCM. The frame length
(in samples) is fixed at construction so Porcupine's expected block size lines
up with what we read from the mic.
"""

from __future__ import annotations

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

    ``sounddevice`` is an optional dependency (``pip install kumi-agent[voice]``);
    importing this class without it raises a clear error.
    """

    def __init__(self, *, sample_rate: int, frame_length: int, device: int | None = None) -> None:
        try:
            import sounddevice as sd  # noqa: F401
        except ImportError as exc:  # pragma: no cover - import-time guard
            raise RuntimeError("sounddevice is not installed. Install with: pip install kumi-agent[voice]") from exc
        self.sample_rate = int(sample_rate)
        self.frame_length = int(frame_length)
        self.device = device
        self._stream = None

    def start(self) -> None:
        import sounddevice as sd

        self._stream = sd.RawInputStream(
            samplerate=self.sample_rate,
            blocksize=self.frame_length,
            dtype="int16",
            channels=1,
            device=self.device,
        )
        self._stream.start()

    def read_frame(self) -> bytes:
        if self._stream is None:
            raise RuntimeError("AudioSource not started")
        data, _overflowed = self._stream.read(self.frame_length)
        # ``data`` is a CFFI buffer for raw streams; bytes(...) is a memcpy.
        return bytes(data)

    def stop(self) -> None:
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            finally:
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
