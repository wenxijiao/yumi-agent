"""Wake-word detection.

Wraps Picovoice Porcupine. The user trains "hi yumi" at console.picovoice.ai
and supplies the resulting ``.ppn`` file path + access key via config or
``PV_ACCESS_KEY`` env var.

Tests use :class:`FakeWake` to drive the loop without the proprietary SDK.
"""

from __future__ import annotations

import os
from typing import Protocol


class WakeDetector(Protocol):
    sample_rate: int
    frame_length: int

    def process(self, frame: bytes) -> bool:
        """Return True iff this frame ended on a wake-word match."""
        ...

    def close(self) -> None: ...


def _resolve_access_key(explicit: str | None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    env = (os.getenv("PV_ACCESS_KEY") or "").strip()
    if env:
        return env
    raise RuntimeError("Picovoice access key missing. Set PV_ACCESS_KEY or voice_porcupine_access_key in config.")


class PorcupineWake:
    """Real Porcupine-backed wake detector."""

    def __init__(
        self,
        *,
        access_key: str | None,
        keyword_path: str | None,
        sensitivity: float = 0.5,
    ) -> None:
        try:
            import pvporcupine  # noqa: F401
        except ImportError as exc:  # pragma: no cover - import-time guard
            raise RuntimeError(
                "pvporcupine is not importable. Reinstall with: pip install --force-reinstall yumi-agent"
            ) from exc
        import pvporcupine

        key = _resolve_access_key(access_key)
        if keyword_path and keyword_path.strip():
            kw_path = os.path.expanduser(keyword_path.strip())
            if not os.path.isfile(kw_path):
                raise RuntimeError(f"Porcupine keyword file not found: {kw_path}")
            self._handle = pvporcupine.create(
                access_key=key,
                keyword_paths=[kw_path],
                sensitivities=[float(sensitivity)],
            )
        else:
            # Fallback to a built-in keyword. "hi yumi" is not built in;
            # users must train a custom .ppn to actually trigger on it.
            self._handle = pvporcupine.create(
                access_key=key,
                keywords=["jarvis"],
                sensitivities=[float(sensitivity)],
            )
        self.sample_rate = int(self._handle.sample_rate)
        self.frame_length = int(self._handle.frame_length)

    def process(self, frame: bytes) -> bool:
        # Porcupine wants a sequence of int16 samples, not bytes.
        import struct

        n = self.frame_length
        if len(frame) != 2 * n:
            return False
        pcm = struct.unpack_from(f"<{n}h", frame)
        return self._handle.process(pcm) >= 0

    def close(self) -> None:
        try:
            self._handle.delete()
        except Exception:
            pass


class FakeWake:
    """Test double: triggers on a pre-set frame index."""

    def __init__(self, *, sample_rate: int = 16000, frame_length: int = 512, trigger_at: int = 0) -> None:
        self.sample_rate = sample_rate
        self.frame_length = frame_length
        self._trigger_at = trigger_at
        self._index = 0
        self.closed = False

    def process(self, frame: bytes) -> bool:
        triggered = self._index == self._trigger_at
        self._index += 1
        return triggered

    def close(self) -> None:
        self.closed = True
