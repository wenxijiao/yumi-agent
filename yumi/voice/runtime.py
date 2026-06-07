"""Voice loop runtime: wake → collect → transcribe → dispatch.

Lifespan-owned asyncio task started when ``YUMI_VOICE_ENABLED=1``. The
blocking microphone read runs in a thread executor so the event loop stays
responsive (Telegram bot, edge sweep, timer callbacks all share the loop).

The loop is split into small pieces for testability:

* :func:`build_voice_components` resolves config + constructs source/wake/vad.
* :func:`run_voice_session` is the pure async loop that takes those pieces +
  a ``transcribe`` callable + a ``dispatch`` callable. Tests pump fake audio
  through this directly and assert on dispatch invocations.
* :func:`start_voice_loop` is the production wiring used by ``app_factory``.
"""

from __future__ import annotations

import asyncio
import io
import wave
from collections.abc import Awaitable, Callable

from yumi.logging_config import get_logger
from yumi.voice.audio_source import AudioSource, SoundDeviceSource
from yumi.voice.segmenter import UtteranceCollector, _VadBackend
from yumi.voice.wake import PorcupineWake, WakeDetector

logger = get_logger(__name__)

TranscribeFn = Callable[[bytes], Awaitable[str]]
DispatchFn = Callable[[str], Awaitable[None]]
VadFn = Callable[[bytes, int], bool]


def pcm_to_wav_bytes(pcm: bytes, *, sample_rate: int) -> bytes:
    """Wrap raw 16-bit mono PCM into an in-memory WAV (so faster-whisper accepts it)."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(int(sample_rate))
        wf.writeframes(pcm)
    return buf.getvalue()


async def _default_transcribe(wav_bytes: bytes) -> str:
    """Hand a WAV blob to the configured Whisper provider."""
    from yumi.core.features.stt.factory import transcribe_audio

    result = await transcribe_audio(wav_bytes, filename="voice.wav")
    return (getattr(result, "text", "") or "").strip()


async def _warm_whisper_once() -> None:
    """Burn the first (slow) Whisper inference on 1s of silence."""
    silence = pcm_to_wav_bytes(b"\x00\x00" * 16000, sample_rate=16000)
    try:
        await _default_transcribe(silence)
        logger.info("voice: whisper warm-up complete")
    except Exception as exc:  # pragma: no cover - degrades gracefully
        logger.warning("voice: whisper warm-up failed: %s", exc)


async def run_voice_session(
    *,
    source: AudioSource,
    wake: WakeDetector,
    collector: UtteranceCollector,
    is_speech: VadFn,
    transcribe: TranscribeFn,
    dispatch: DispatchFn,
    stop_event: asyncio.Event,
) -> None:
    """Pump frames; on wake-word, collect until silence; transcribe; dispatch.

    ``is_speech`` takes ``(frame_bytes, sample_rate)``. ``transcribe`` takes
    a WAV blob and returns text. ``dispatch`` takes the text and runs whatever
    the operator wants (in production: ``voice_dispatch``).
    """
    loop = asyncio.get_running_loop()
    try:
        source.start()
    except Exception:
        # Source.start() may fail before any resource is held; still close the wake detector
        # so the Porcupine native handle isn't leaked for the rest of the process lifetime.
        try:
            wake.close()
        except Exception:
            pass
        raise
    logger.info("voice: listening (sample_rate=%d, frame_length=%d)", source.sample_rate, source.frame_length)
    collecting = False
    try:
        while not stop_event.is_set():
            frame = await loop.run_in_executor(None, source.read_frame)
            if not collecting:
                if wake.process(frame):
                    logger.info("voice: wake-word triggered")
                    collector.reset()
                    collecting = True
                continue
            speech = bool(is_speech(frame, source.sample_rate))
            utterance = collector.feed(frame, is_speech=speech)
            if utterance is None:
                continue
            collecting = False
            duration_ms = int(round(1000 * len(utterance) / 2 / source.sample_rate))
            logger.info("voice: utterance captured %d ms", duration_ms)
            wav = pcm_to_wav_bytes(utterance, sample_rate=source.sample_rate)
            try:
                text = await transcribe(wav)
            except Exception as exc:
                logger.warning("voice: transcription failed: %s", exc)
                continue
            text = (text or "").strip()
            if not text:
                logger.info("voice: empty transcript, skipping")
                continue
            logger.info("voice: transcript=%r", text)
            try:
                await dispatch(text)
            except Exception as exc:
                logger.exception("voice: dispatch failed: %s", exc)
    finally:
        try:
            source.stop()
        except Exception:
            pass
        try:
            wake.close()
        except Exception:
            pass


def build_voice_components(cfg) -> tuple[AudioSource, WakeDetector, UtteranceCollector, VadFn]:
    """Construct the production audio source / wake / VAD from a ModelConfig."""
    wake = PorcupineWake(
        access_key=cfg.voice_porcupine_access_key,
        keyword_path=cfg.voice_porcupine_keyword_path,
        sensitivity=cfg.voice_porcupine_sensitivity,
    )
    try:
        source = SoundDeviceSource(
            sample_rate=wake.sample_rate,
            frame_length=wake.frame_length,
            device=cfg.voice_input_device,
        )
        collector = UtteranceCollector(
            sample_rate=wake.sample_rate,
            frame_length=wake.frame_length,
            silence_ms=cfg.voice_silence_ms,
            max_ms=cfg.voice_max_utterance_ms,
        )
        vad_backend = _VadBackend(cfg.voice_vad_aggressiveness)
    except Exception:
        # Release the Porcupine native handle if downstream construction failed.
        try:
            wake.close()
        except Exception:
            pass
        raise

    def is_speech(frame: bytes, sample_rate: int) -> bool:
        # webrtcvad needs exactly 10/20/30 ms frames. Slice the Porcupine block
        # into 30 ms windows; if any window classifies as speech, the frame is.
        window_samples = int(sample_rate * 30 / 1000)
        window_bytes = window_samples * 2
        if window_bytes <= 0 or len(frame) < window_bytes:
            return False
        for offset in range(0, len(frame) - window_bytes + 1, window_bytes):
            chunk = frame[offset : offset + window_bytes]
            if vad_backend.is_speech(chunk, sample_rate):
                return True
        return False

    return source, wake, collector, is_speech


async def start_voice_loop(
    *,
    owner_id: str,
    dispatch: DispatchFn,
    cfg=None,
    stop_event: asyncio.Event | None = None,
) -> tuple[asyncio.Task, asyncio.Event, AudioSource]:
    """Build voice components from config, kick off the loop as a background task.

    Returns ``(task, stop_event, source)``. The caller (lifespan) signals
    shutdown by setting the event AND calling ``source.stop()`` so the
    blocking ``read_frame`` in the executor returns promptly.
    """
    if cfg is None:
        from yumi.core.features.config import load_model_config

        cfg = load_model_config()
    source, wake, collector, is_speech = build_voice_components(cfg)
    stop = stop_event or asyncio.Event()

    async def _run() -> None:
        await run_voice_session(
            source=source,
            wake=wake,
            collector=collector,
            is_speech=is_speech,
            transcribe=_default_transcribe,
            dispatch=dispatch,
            stop_event=stop,
        )

    task = asyncio.create_task(_run(), name=f"voice_loop:{owner_id}")
    return task, stop, source
