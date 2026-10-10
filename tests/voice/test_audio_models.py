from __future__ import annotations

import asyncio
import io
import wave

import numpy as np
import pytest
from yumi.voice.duplex import DuplexAudio, decode_audio
from yumi.voice.models import install_archive
from yumi.voice.segmenter import UtteranceCollector


def test_silence_never_becomes_a_recording():
    collector = UtteranceCollector(sample_rate=16000, frame_length=1600)
    for _ in range(200):
        assert collector.feed(bytes(3200), is_speech=False) is None
    assert not collector._frames


def test_wav_decodes_and_resamples_without_external_player():
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(48000)
        wav.writeframes(np.tile(np.array([1000, 1000], dtype=np.int16), 4800).tobytes())
    pcm = decode_audio(output.getvalue(), 16000)
    assert len(pcm) == 3200
    assert np.abs(np.frombuffer(pcm, dtype=np.int16).mean() - 1000) < 2


def test_unverified_model_is_not_extracted(tmp_path):
    archive = tmp_path / "bad.tar.bz2"
    archive.write_bytes(b"corrupt")
    with pytest.raises(RuntimeError, match="checksum"):
        install_archive(archive, tmp_path)
    assert list(tmp_path.iterdir()) == [archive]


def test_duplex_callback_uses_render_reference_and_interrupt_flushes(monkeypatch):
    class Stream:
        def __init__(self, **kwargs):
            self.callback = kwargs["callback"]

        def abort(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr("yumi.voice.duplex.device_settings", lambda *_: (16000, 2, "mic", "speaker"))
    monkeypatch.setattr("yumi.voice.duplex.sd.RawStream", Stream)
    audio = DuplexAudio()
    references = []

    class AEC:
        def process(self, near, far):
            references.append(far.copy())
            return near

    audio._ap = AEC()
    render = np.full(160, 1000, dtype=np.int16).tobytes()
    audio._render.append(render)
    out = bytearray(640)
    audio._callback(bytes(320), out, 160, None, None)
    assert references[0].tolist() == [1000] * 160
    assert np.frombuffer(out, dtype=np.int16).tolist() == [1000] * 320
    audio._render.append(render)
    audio.interrupt()
    audio._callback(bytes(320), out, 160, None, None)
    assert out == bytes(640)
    for _ in range(8):
        audio._callback(bytes(320), out, 160, None, None)
    assert len(asyncio.run(audio.read_frame())) == 3200
    audio.close()


def test_local_cues_are_short_faded_and_audible():
    from yumi.voice.cues import PATTERNS, cue_pcm

    for kind in PATTERNS:
        pcm = np.frombuffer(cue_pcm(kind, 48000), dtype="<i2")
        assert 0.09 < len(pcm) / 48000 < 0.4
        assert 4000 < np.max(np.abs(pcm)) <= 5250
        assert pcm[0] == pcm[-1] == 0


def test_separate_usb_microphone_is_preferred_for_narrowband_default(monkeypatch):
    from yumi.voice.duplex import select_input_device

    devices = [
        dict(name="Bluetooth", max_input_channels=1, default_samplerate=8000),
        dict(name="Bluetooth", max_input_channels=0, default_samplerate=44100),
        dict(name="USB Microphone", max_input_channels=1, default_samplerate=48000),
    ]

    def query(device=None, kind=None):
        if device is not None:
            return devices[device]
        if kind == "input":
            return devices[0]
        if kind == "output":
            return devices[1]
        return devices

    monkeypatch.setattr("yumi.voice.duplex.sd.query_devices", query)
    assert select_input_device() == 2
    assert select_input_device(0) == 0


def test_no_alternative_mic_explains_quality_and_pause(monkeypatch, capsys):
    from yumi.voice.duplex import select_input_device

    mic = dict(name="Bluetooth", max_input_channels=1, default_samplerate=8000)
    monkeypatch.setattr("yumi.voice.duplex.sd.query_devices", lambda device=None, kind=None: mic if kind else [mic])
    assert select_input_device() is None
    assert "pause microphone" in capsys.readouterr().out


def test_cue_volume_can_be_adjusted_or_muted_without_clipping():
    from yumi.voice.cues import cue_pcm

    assert not np.any(np.frombuffer(cue_pcm("wake", 8000, 0), dtype=np.int16))
    loud = np.frombuffer(cue_pcm("wake", 8000, 100), dtype=np.int16)
    quiet = np.frombuffer(cue_pcm("wake", 8000, 50), dtype=np.int16)
    assert np.max(np.abs(loud)) <= 7500
    assert np.max(np.abs(loud)) > np.max(np.abs(quiet)) * 1.9
    with pytest.raises(ValueError):
        cue_pcm("wake", 8000, 101)
