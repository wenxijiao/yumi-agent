"""Normalize browser-recorded audio to WAV for cloud STT providers.

Chrome/Firefox ``MediaRecorder`` emit WebM/Opus and Safari/iOS emit MP4/AAC.
Several cloud STT APIs (Gemini inline audio, DashScope, Grok) do not accept
those containers, so we transcode to 16 kHz mono PCM WAV using PyAV (``av``),
which ships with faster-whisper and bundles the ffmpeg libraries (no system
ffmpeg required). Local Whisper and OpenAI accept the originals and skip this.

Best-effort: if PyAV is missing or the transcode fails, the original bytes are
returned unchanged so the caller can still try (and fail with its own error).
"""

from __future__ import annotations

import io

from yumi.logging_config import get_logger

logger = get_logger(__name__)

_WEBM_MAGIC = b"\x1a\x45\xdf\xa3"  # EBML header (WebM / Matroska)


def is_browser_container(audio: bytes, filename: str) -> bool:
    """True for WebM (Chrome/Firefox) or MP4/M4A (Safari) browser recordings."""
    if len(audio) >= 4 and audio[:4] == _WEBM_MAGIC:
        return True
    if len(audio) >= 12 and audio[4:8] == b"ftyp":  # ISO base media (mp4/m4a)
        return True
    name = (filename or "").lower()
    return name.endswith((".webm", ".mp4", ".m4a"))


def to_wav_if_browser_audio(audio: bytes, filename: str) -> tuple[bytes, str]:
    """Transcode webm/mp4 recordings to 16 kHz mono WAV; pass everything else through."""
    if not audio or not is_browser_container(audio, filename):
        return audio, filename
    try:
        import av
    except Exception:
        logger.debug("PyAV unavailable; forwarding original audio container to STT")
        return audio, filename
    try:
        out = io.BytesIO()
        with av.open(io.BytesIO(audio)) as inp, av.open(out, mode="w", format="wav") as outp:
            ostream = outp.add_stream("pcm_s16le", rate=16000)
            try:
                ostream.layout = "mono"
            except Exception:
                pass
            resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
            for frame in inp.decode(audio=0):
                resampled = resampler.resample(frame)
                frames = resampled if isinstance(resampled, list) else [resampled]
                for rframe in frames:
                    for pkt in ostream.encode(rframe):
                        outp.mux(pkt)
            for pkt in ostream.encode(None):
                outp.mux(pkt)
        data = out.getvalue()
        if data:
            return data, "audio.wav"
    except Exception as exc:
        logger.debug("Browser audio transcode failed (%s); forwarding original", exc)
    return audio, filename
