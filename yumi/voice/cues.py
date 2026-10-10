"""Short local earcons; available before any network speech request."""

from __future__ import annotations

import numpy as np

PATTERNS = {
    "ready": [(550, 0.14)],
    "wake": [(660, 0.12), (990, 0.18)],
    "followup": [(880, 0.10)],
    "submit": [(660, 0.08)],
    "sleep": [(740, 0.09), (440, 0.12)],
    "pause": [(440, 0.15)],
    "retry": [(330, 0.06), (330, 0.06)],
}


def cue_pcm(kind: str, rate: int, volume: int = 70) -> bytes:
    if not 0 <= volume <= 100:
        raise ValueError("Cue volume must be between 0 and 100")
    chunks = []
    for frequency, duration in PATTERNS[kind]:
        count = round(rate * duration)
        # Smooth envelope avoids clicks; no speech or network dependency.
        envelope = np.sin(np.linspace(0, np.pi, count)) ** 2
        signal = np.sin(2 * np.pi * frequency * np.arange(count) / rate)
        chunks.append((signal * envelope * (7500 * volume / 100)).astype("<i2").tobytes())
        chunks.append(bytes(round(rate * 0.02) * 2))
    return b"".join(chunks)
