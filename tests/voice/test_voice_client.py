from __future__ import annotations

import argparse
import json
from types import SimpleNamespace

from yumi.cli.commands import build_default_registry, validate_cross_command_flags
from yumi.voice.client import VoiceConnection, logout_nexus, voice_turn
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


def test_voice_client_command_is_standalone():
    parser = argparse.ArgumentParser()
    build_default_registry().install(parser)
    args = parser.parse_args(["--voice-client", "--voice-mode", "nexus"])
    assert args.voice_client
    assert args.voice_mode == "nexus"
    assert validate_cross_command_flags(args) is None


def test_voice_turn_uses_personal_account_voice_pipeline(monkeypatch):
    calls = []
    played = []

    def request(self, method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path == "/assistant":
            return Response({"session_id": "u_alice__personal_1", "revision": 4})
        if path == "/assistant/voice":
            return Response({"id": "voice-1", "transcript": "set a reminder"})
        if path == "/chat":
            return Response(events=[
                {"type": "turn_phase", "turn_id": "turn-1", "phase": "preparing"},
                {"type": "text", "content": "Done."},
            ])
        if path == "/assistant/voice/reply":
            return Response({"id": "reply-1", "part_count": 1})
        if path == "/assistant/voice/reply-1/audio?part=0":
            return Response()
        raise AssertionError(path)

    monkeypatch.setattr(VoiceConnection, "request", request)
    monkeypatch.setattr("yumi.core.features.tts.playback.play_audio", played.append)
    assert voice_turn(VoiceConnection("https://api.yumi.nexus", "token"), b"RIFFdemo") == "Done."
    upload = calls[1][2]["json"]
    chat = calls[2][2]["json"]
    assert upload["session_id"] == "u_alice__personal_1"
    assert chat["personal"] is True
    assert chat["voice_id"] == "voice-1"
    assert chat["revision"] == 4
    assert played[0].data == b"RIFFdemo"


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
