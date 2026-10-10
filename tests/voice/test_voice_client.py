from __future__ import annotations

import argparse
import json
from types import SimpleNamespace

import pytest
from yumi.cli.commands import build_default_registry, validate_cross_command_flags
from yumi.voice.client import VoiceConnection, choose_mode, logout_nexus
from yumi.voice.sherpa_wake import SherpaHeyYumiWake


class Response:
    headers = {"content-type": "audio/wav"}
    content = b"RIFFdemo"

    def __init__(self, payload=None, events=None):
        self.payload = payload or {}
        self.events = events or []

    def json(self):
        return self.payload

    def iter_lines(self):
        return [json.dumps(item).encode() for item in self.events]

    def close(self):
        pass


def test_voice_command_is_standalone():
    parser = argparse.ArgumentParser()
    build_default_registry().install(parser)
    args = parser.parse_args(["--voice", "--voice-mode", "nexus"])
    assert args.voice
    assert args.voice_mode == "nexus"
    assert validate_cross_command_flags(args) is None


def test_voice_audio_mode_is_explicit_and_scoped_to_voice():
    parser = argparse.ArgumentParser()
    build_default_registry().install(parser)
    args = parser.parse_args(["--voice", "--voice-audio-mode", "half-duplex"])
    assert args.voice_audio_mode == "half-duplex"
    assert validate_cross_command_flags(args) is None
    args = parser.parse_args(["--voice-audio-mode", "half-duplex"])
    assert validate_cross_command_flags(args) is not None
    with pytest.raises(SystemExit):
        parser.parse_args(["--voice", "--voice-audio-mode", "invalid"])


def test_voice_menu_offers_local_or_nexus(monkeypatch, capsys):
    monkeypatch.setattr("yumi.voice.client.sys.stdin", SimpleNamespace(isatty=lambda: True))
    answers = iter(["bad", "2"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    assert choose_mode() == "nexus"
    output = capsys.readouterr().out
    assert "Local model" in output
    assert "Yumi Nexus" in output


def test_voice_without_terminal_requires_explicit_mode(monkeypatch):
    monkeypatch.setattr("yumi.voice.client.sys.stdin", SimpleNamespace(isatty=lambda: False))
    with pytest.raises(SystemExit, match="--voice-mode"):
        choose_mode()


def test_wake_hit_is_checked_after_each_decode():
    import numpy as np

    class Spotter:
        def __init__(self):
            self.chunks = ["HEY YUMI", ""]
            self.result = ""
            self.reset = False

        def is_ready(self, stream):
            return bool(self.chunks)

        def decode_stream(self, stream):
            self.result = self.chunks.pop(0)

        def get_result(self, stream):
            return self.result

        def reset_stream(self, stream):
            self.reset = True

    class Stream:
        def accept_waveform(self, sample_rate, samples):
            assert sample_rate == 16000
            assert len(samples) == 1600

    wake = SherpaHeyYumiWake.__new__(SherpaHeyYumiWake)
    wake._np = np
    wake._spotter = Spotter()
    wake._stream = Stream()
    assert wake.process(b"\0\0" * 1600) is True
    assert wake._spotter.reset is True


def test_server_voice_mode_uses_shared_hey_yumi_engine(monkeypatch):
    from yumi.voice import runtime

    class Wake:
        sample_rate = 16000
        frame_length = 1600

        def __init__(self, model_dir, keywords_file):
            assert (model_dir, keywords_file) == ("/model", None)

        def close(self):
            pass

    monkeypatch.setattr(runtime, "SherpaHeyYumiWake", Wake)
    monkeypatch.setattr(runtime, "SoundDeviceSource", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(runtime, "_VadBackend", lambda aggressiveness: SimpleNamespace(is_speech=lambda *_: False))
    cfg = SimpleNamespace(
        voice_sherpa_model_dir="/model",
        voice_sherpa_keywords_file=None,
        voice_input_device=None,
        voice_silence_ms=800,
        voice_max_utterance_ms=15000,
        voice_vad_aggressiveness=2,
    )
    source, wake, collector, _ = runtime.build_voice_components(cfg)
    assert isinstance(wake, Wake)
    assert source.frame_length == collector.frame_length == 1600


def test_voice_logout_revokes_nexus_credential_before_removing_local_copy(monkeypatch, tmp_path):
    credential = tmp_path / "voice-client.json"
    credential.write_text(json.dumps({"server": "https://api.yumi.nexus", "access_token": "token"}))
    monkeypatch.setattr("yumi.voice.client.CLIENT_FILE", credential)
    calls = []

    def request(self, method, path, **kwargs):
        calls.append((method, path))
        if path == "/tenancy/connections":
            return Response({"connections": [{"id": "voice-device", "kind": "voice", "current": True}]})
        if path == "/tenancy/connections/voice-device":
            assert credential.exists()
            return Response({"status": "removed"})
        raise AssertionError(path)

    monkeypatch.setattr(VoiceConnection, "request", request)
    logout_nexus()
    assert calls == [("GET", "/tenancy/connections"), ("DELETE", "/tenancy/connections/voice-device")]
    assert not credential.exists()


def test_microphone_stop_unblocks_pending_read(monkeypatch):
    import threading

    from yumi.voice.audio_source import SoundDeviceSource

    class Stream:
        def __init__(self, **kwargs):
            self.callback = kwargs["callback"]

        def start(self):
            pass

        def abort(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr("sounddevice.RawInputStream", Stream)
    source = SoundDeviceSource(sample_rate=16000, frame_length=1600)
    source.start()
    heard = []
    reader = threading.Thread(target=lambda: heard.append(source.read_frame()))
    reader.start()
    source.stop()
    reader.join(timeout=1)
    assert not reader.is_alive()
    assert heard == [b"\0\0" * 1600]


def test_voice_feedback_options_are_bounded_and_require_voice_mode():
    parser = argparse.ArgumentParser()
    build_default_registry().install(parser)
    args = parser.parse_args(["--voice", "--voice-wake-sensitivity", "high", "--voice-cue-volume", "90"])
    assert (args.voice_wake_sensitivity, args.voice_cue_volume) == ("high", 90)
    assert validate_cross_command_flags(args) is None
    with pytest.raises(SystemExit):
        parser.parse_args(["--voice", "--voice-cue-volume", "101"])
    assert validate_cross_command_flags(parser.parse_args(["--voice-cue-volume", "0"]))
