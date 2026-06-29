"""On-demand optional-feature installer used by the setup wizard and CLI."""

import subprocess
import sys

from yumi.core.features.config import feature_install as fi


def test_extra_requirements_reads_installed_metadata(monkeypatch):
    monkeypatch.setattr(
        fi,
        "_dist_requires",
        lambda _dist: [
            "reflex>=0.9; extra == 'ui'",
            "qwen-tts; extra == 'tts-local'",
            "fastembed>=0.6",
        ],
    )
    reqs = " ".join(fi._extra_requirements("ui"))
    assert "reflex" in reqs
    # STT/voice/TTS provider deps are now in the base, not extras.
    assert fi._extra_requirements("stt") == []
    assert fi._extra_requirements("nope") == []


def test_only_heavy_features_are_registered():
    assert set(fi._FEATURES) == {"ui", "tts-local"}
    assert fi._FEATURES["ui"] == ("ui", "reflex", "the Reflex web UI")
    assert fi._FEATURES["tts-local"] == ("tts-local", "qwen_tts", "Qwen3-TTS running locally (GPU)")


def test_already_installed_is_a_noop(monkeypatch):
    monkeypatch.setattr(fi, "is_feature_installed", lambda f: True)
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a))
    assert fi.ensure_feature_installed("ui") is True
    assert calls == []  # never shelled out to pip


def test_decline_does_not_install(monkeypatch):
    monkeypatch.setattr(fi, "is_feature_installed", lambda f: False)
    monkeypatch.setattr("builtins.input", lambda *a: "n")
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a))
    assert fi.ensure_feature_installed("ui") is False
    assert calls == []


def test_assume_yes_installs_the_extra_requirements(monkeypatch):
    states = iter([False, True])  # missing -> install -> importable
    monkeypatch.setattr(fi, "is_feature_installed", lambda f: next(states))
    monkeypatch.setattr(fi, "_extra_requirements", lambda extra: ["reflex>=0.9"] if extra == "ui" else [])
    captured = {}
    monkeypatch.setattr(subprocess, "run", lambda cmd, check: captured.update(cmd=cmd))

    assert fi.ensure_feature_installed("ui", assume_yes=True) is True
    assert captured["cmd"][:4] == [sys.executable, "-m", "pip", "install"]
    assert any("reflex" in t for t in captured["cmd"][4:])


def test_assume_yes_does_not_prompt_or_print_optional_package_notice(monkeypatch, capsys):
    states = iter([False, True])  # missing -> install -> importable
    monkeypatch.setattr(fi, "is_feature_installed", lambda f: next(states))
    monkeypatch.setattr(fi, "_extra_requirements", lambda extra: ["qwen-tts"] if extra == "tts-local" else [])
    monkeypatch.setattr("builtins.input", lambda *a: (_ for _ in ()).throw(AssertionError("should not prompt")))
    monkeypatch.setattr(subprocess, "run", lambda cmd, check: None)

    assert fi.ensure_feature_installed("tts-local", assume_yes=True) is True

    out = capsys.readouterr().out
    assert "needs an optional package" not in out
    assert "Install it now?" not in out
    assert "Installing:" in out


def test_install_that_stays_unimportable_returns_false(monkeypatch):
    monkeypatch.setattr(fi, "is_feature_installed", lambda f: False)  # never becomes importable
    monkeypatch.setattr(subprocess, "run", lambda cmd, check: None)
    assert fi.ensure_feature_installed("ui", assume_yes=True) is False
