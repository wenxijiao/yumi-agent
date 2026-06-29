"""Voice activity detection + utterance segmentation.

Once the wake word fires, the runtime switches into "collect" mode and feeds
incoming frames to :class:`UtteranceCollector` until the speaker pauses (silence
exceeds ``silence_ms``) or the utterance hits ``max_ms``.

WebRTC VAD requires 10/20/30 ms frames at 8/16/32/48 kHz, mono int16. We
target 16 kHz with whatever frame length Porcupine demands (typically 32 ms /
512 samples) — slightly off-spec for VAD, so we slice each Porcupine frame
into 30 ms VAD windows internally.
"""

from __future__ import annotations


class _VadBackend:
    """Wraps either webrtcvad or a stub used in tests."""

    def __init__(self, aggressiveness: int) -> None:
        try:
            import webrtcvad  # noqa: F401
        except ImportError as exc:  # pragma: no cover - import-time guard
            raise RuntimeError(
                "webrtcvad is not importable. Reinstall with: pip install --force-reinstall yumi"
            ) from exc
        import webrtcvad

        self._vad = webrtcvad.Vad(int(aggressiveness))

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        return bool(self._vad.is_speech(frame, sample_rate))


class FakeVad:
    """Test double; classifies frames as speech if their first byte != 0."""

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        return bool(frame) and frame[0] != 0


class UtteranceCollector:
    """Accumulates PCM until silence_ms of trailing silence or max_ms total."""

    def __init__(
        self,
        *,
        sample_rate: int,
        frame_length: int,
        silence_ms: int = 800,
        max_ms: int = 15000,
    ) -> None:
        self.sample_rate = sample_rate
        self.frame_length = frame_length
        self.silence_ms = max(100, silence_ms)
        self.max_ms = max(1000, max_ms)
        self._frame_ms = max(1, int(round(1000 * frame_length / max(1, sample_rate))))
        self._frames: list[bytes] = []
        self._trailing_silence_ms = 0
        self._elapsed_ms = 0

    def reset(self) -> None:
        self._frames.clear()
        self._trailing_silence_ms = 0
        self._elapsed_ms = 0

    def feed(self, frame: bytes, *, is_speech: bool) -> bytes | None:
        """Append ``frame``; return the joined PCM when the utterance ends.

        Returns ``None`` while collecting. Once an end-of-utterance condition
        is met the collector's internal state is cleared and the caller gets
        the full PCM (suitable for wrapping into a WAV).
        """
        self._frames.append(frame)
        self._elapsed_ms += self._frame_ms
        if is_speech:
            self._trailing_silence_ms = 0
        else:
            self._trailing_silence_ms += self._frame_ms
        if self._trailing_silence_ms >= self.silence_ms or self._elapsed_ms >= self.max_ms:
            pcm = b"".join(self._frames)
            self.reset()
            return pcm
        return None
