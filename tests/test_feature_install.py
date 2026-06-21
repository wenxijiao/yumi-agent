"""On-demand optional-feature installer used by the setup wizard and CLI."""

import subprocess
import sys

from yumi.core.features.config import feature_install as fi


def test_extra_requirements_reads_installed_metadata():
    reqs = " ".join(fi._extra_requirements("stt"))
    assert "faster-whisper" in reqs
    assert "huggingface-hub" in reqs
    # provider/bridge deps are now in the base, not extras
    assert fi._extra_requirements("openai") == []
    assert fi._extra_requirements("nope") == []


def test_embed_feature_is_registered():
    assert fi._FEATURES["embed"] == ("embed", "fastembed", "local multilingual embeddings")


def test_already_installed_is_a_noop(monkeypatch):
    monkeypatch.setattr(fi, "is_feature_installed", lambda f: True)
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a))
    assert fi.ensure_feature_installed("stt") is True
    assert calls == []  # never shelled out to pip


def test_decline_does_not_install(monkeypatch):
    monkeypatch.setattr(fi, "is_feature_installed", lambda f: False)
    monkeypatch.setattr("builtins.input", lambda *a: "n")
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a))
    assert fi.ensure_feature_installed("stt") is False
    assert calls == []


def test_assume_yes_installs_the_extra_requirements(monkeypatch):
    states = iter([False, True])  # missing -> install -> importable
    monkeypatch.setattr(fi, "is_feature_installed", lambda f: next(states))
    captured = {}
    monkeypatch.setattr(subprocess, "run", lambda cmd, check: captured.update(cmd=cmd))

    assert fi.ensure_feature_installed("voice", assume_yes=True) is True
    assert captured["cmd"][:4] == [sys.executable, "-m", "pip", "install"]
    assert any("sounddevice" in t for t in captured["cmd"][4:])


def test_install_that_stays_unimportable_returns_false(monkeypatch):
    monkeypatch.setattr(fi, "is_feature_installed", lambda f: False)  # never becomes importable
    monkeypatch.setattr(subprocess, "run", lambda cmd, check: None)
    assert fi.ensure_feature_installed("voice", assume_yes=True) is False
