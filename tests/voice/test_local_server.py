from types import SimpleNamespace

import pytest
import requests
from yumi.voice.local_server import local_server


def test_existing_server_is_reused_and_body_error_does_not_start_another(monkeypatch):
    connection = SimpleNamespace(request=lambda *_, **__: None)
    monkeypatch.setattr(
        "yumi.voice.local_server.subprocess.Popen", lambda *_, **__: pytest.fail("must not start a server")
    )
    with pytest.raises(requests.ConnectionError):
        with local_server(connection, auto_start=True):
            raise requests.ConnectionError("voice request disconnected")


def test_owned_local_server_enables_speech_and_is_stopped(monkeypatch, tmp_path):
    import yumi.cli.runners as runners
    import yumi.core.features.config as config_module

    config = SimpleNamespace(stt_provider="disabled", stt_model=None, tts_provider="disabled")
    saved, spawned, terminated = [], [], []
    monkeypatch.setattr(runners, "_preflight_models", lambda: config)
    monkeypatch.setattr(config_module, "save_model_config", saved.append)
    monkeypatch.setattr("yumi.core.features.tts.system_provider.resolve_system_command", lambda: "say")
    monkeypatch.setattr("yumi.voice.local_server.Path.home", lambda: tmp_path)

    def spawn(argv, **kwargs):
        spawned.append((argv, kwargs))
        return SimpleNamespace(poll=lambda: None, terminate=lambda: terminated.append(True), wait=lambda **_: None)

    monkeypatch.setattr("yumi.voice.local_server.subprocess.Popen", spawn)
    requests_made = []

    def request(*_, **__):
        requests_made.append(True)
        if len(requests_made) == 1:
            raise requests.ConnectionError()

    with local_server(SimpleNamespace(request=request), auto_start=True):
        assert config.stt_provider == "whisper"
        assert config.tts_provider == "system"
        assert not terminated
    assert terminated == [True]
    assert saved == [config]
    assert spawned[0][1]["env"]["YUMI_HOST"] == "127.0.0.1"


def test_custom_server_is_never_autostarted():
    def request(*_, **__):
        raise requests.ConnectionError()

    with pytest.raises(RuntimeError, match="Cannot reach"):
        with local_server(SimpleNamespace(request=request, base_url="http://localhost:9000"), auto_start=False):
            pytest.fail("unreachable server")
