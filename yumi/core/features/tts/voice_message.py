"""Helpers for messaging-platform voice-note delivery."""

from __future__ import annotations

import base64
import io
import shutil
import struct
import subprocess
from dataclasses import dataclass

from yumi.core.features.tts.types import SpeechAudio

_VOICE_RATE = 48_000
_WAVEFORM_POINTS = 128


@dataclass(frozen=True)
class VoiceMessageAudio:
    data: bytes
    duration_secs: float
    waveform: str


def to_ogg_opus_voice(audio: SpeechAudio) -> VoiceMessageAudio:
    """Return a 48kHz mono OGG/Opus clip plus metadata for voice-message UIs."""

    try:
        return _to_ogg_opus_with_ffmpeg(audio.data)
    except Exception:
        return _to_ogg_opus_with_pyav(audio.data)


def _to_ogg_opus_with_ffmpeg(raw: bytes) -> VoiceMessageAudio:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not installed")

    pcm = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-ac",
            "1",
            "-ar",
            str(_VOICE_RATE),
            "-f",
            "s16le",
            "pipe:1",
        ],
        input=raw,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout

    ogg = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-ac",
            "1",
            "-ar",
            str(_VOICE_RATE),
            "-c:a",
            "libopus",
            "-b:a",
            "32k",
            "-vbr",
            "off",
            "-f",
            "ogg",
            "pipe:1",
        ],
        input=raw,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    ).stdout

    return VoiceMessageAudio(
        data=ogg,
        duration_secs=_duration_secs(pcm),
        waveform=_waveform_from_pcm16(pcm),
    )


def _to_ogg_opus_with_pyav(raw: bytes) -> VoiceMessageAudio:
    import av
    import numpy as np
    from av.audio.resampler import AudioResampler

    source = av.open(io.BytesIO(raw))
    out_buf = io.BytesIO()
    output = av.open(out_buf, mode="w", format="ogg")
    try:
        try:
            stream = output.add_stream("libopus", rate=_VOICE_RATE)
        except Exception:
            stream = output.add_stream("opus", rate=_VOICE_RATE)
        stream.layout = "mono"
        stream.bit_rate = 32_000
        resampler = AudioResampler(format="s16", layout="mono", rate=_VOICE_RATE)
        pcm_chunks: list[bytes] = []

        for frame in source.decode(audio=0):
            for resampled in resampler.resample(frame):
                arr = resampled.to_ndarray()
                if arr.ndim > 1:
                    arr = arr.reshape(-1)
                pcm_chunks.append(np.asarray(arr, dtype="<i2").tobytes())
                for packet in stream.encode(resampled):
                    output.mux(packet)
        for resampled in resampler.resample(None):
            arr = resampled.to_ndarray()
            if arr.ndim > 1:
                arr = arr.reshape(-1)
            pcm_chunks.append(np.asarray(arr, dtype="<i2").tobytes())
            for packet in stream.encode(resampled):
                output.mux(packet)
        for packet in stream.encode(None):
            output.mux(packet)
    finally:
        output.close()
        source.close()

    pcm = b"".join(pcm_chunks)
    return VoiceMessageAudio(
        data=out_buf.getvalue(),
        duration_secs=_duration_secs(pcm),
        waveform=_waveform_from_pcm16(pcm),
    )


def _duration_secs(pcm16: bytes) -> float:
    if not pcm16:
        return 0.1
    return max(0.1, len(pcm16) / 2 / _VOICE_RATE)


def _waveform_from_pcm16(pcm16: bytes) -> str:
    if not pcm16:
        return base64.b64encode(bytes([128] * _WAVEFORM_POINTS)).decode("ascii")

    sample_count = len(pcm16) // 2
    step = max(1, sample_count // _WAVEFORM_POINTS)
    points = bytearray()
    max_sample = 1
    samples = struct.iter_unpack("<h", pcm16[: sample_count * 2])
    values = [abs(s[0]) for s in samples]
    if values:
        max_sample = max(max(values), 1)
    for i in range(0, sample_count, step):
        window = values[i : i + step]
        amp = max(window) if window else 0
        points.append(min(255, max(0, int(amp / max_sample * 255))))
        if len(points) >= _WAVEFORM_POINTS:
            break
    while len(points) < _WAVEFORM_POINTS:
        points.append(0)
    return base64.b64encode(bytes(points)).decode("ascii")
