"""Setup-flow behaviour: optional embeddings, env auto-detect, non-interactive config.

These cover the cloud-first / local-optional setup rework: a chat model can be
inferred from a bare API key (Docker-friendly), embeddings default to off, and
`yumi --setup --provider ...` configures everything without prompts.
"""

import json
import os

import pytest
from yumi.core.features.config import configure_models_noninteractive, credentials
from yumi.core.features.config.model import ModelConfig, embeddings_enabled


@pytest.fixture
def isolated_config(monkeypatch, tmp_path):
    """Empty config file + cleared model env so detection is fully controlled."""
    p = tmp_path / "config.json"
    p.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("yumi.core.features.config.paths.CONFIG_PATH", p)
    monkeypatch.setattr("yumi.core.features.config.store.CONFIG_PATH", p)
    # isolate env mutations (e.g. _persist_cloud_api_key writes os.environ directly)
    monkeypatch.setattr(os, "environ", dict(os.environ))
    for k in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "DEEPSEEK_API_KEY",
        "YUMI_CHAT_PROVIDER",
        "YUMI_CHAT_MODEL",
    ):
        os.environ.pop(k, None)
    return p


# ── embeddings_enabled ───────────────────────────────────────────────────────


def test_embeddings_enabled_true_when_model_set():
    assert embeddings_enabled(ModelConfig(chat_model="m", embedding_provider="ollama", embedding_model="e"))


def test_embeddings_disabled_without_model():
    assert not embeddings_enabled(ModelConfig(chat_model="m", embedding_model=None))


def test_embeddings_disabled_with_sentinel_provider():
    assert not embeddings_enabled(ModelConfig(chat_model="m", embedding_provider="disabled", embedding_model="e"))


# ── env auto-detect ──────────────────────────────────────────────────────────


def test_infer_from_openai_key(isolated_config):
    os.environ["OPENAI_API_KEY"] = "sk-test"
    assert credentials.infer_chat_from_env() == ("openai", "gpt-4o")


def test_infer_explicit_provider_beats_key(isolated_config):
    os.environ["OPENAI_API_KEY"] = "sk-test"
    os.environ["YUMI_CHAT_PROVIDER"] = "claude"
    assert credentials.infer_chat_from_env() == ("claude", "claude-sonnet-4-6")


def test_infer_none_when_nothing_set(isolated_config):
    assert credentials.infer_chat_from_env() is None


def test_ensure_chat_model_autodetects_and_persists(isolated_config):
    os.environ["GEMINI_API_KEY"] = "g-test"
    cfg = credentials.ensure_chat_model_configured(interactive=False)
    assert (cfg.chat_provider, cfg.chat_model) == ("gemini", "gemini-2.0-flash")
    saved = json.loads(isolated_config.read_text(encoding="utf-8"))
    assert saved["chat_model"] == "gemini-2.0-flash"


def test_ensure_chat_model_raises_without_anything(isolated_config):
    with pytest.raises(RuntimeError):
        credentials.ensure_chat_model_configured(interactive=False)


# ── non-interactive config ───────────────────────────────────────────────────


def test_noninteractive_cloud_defaults_embeddings_off(isolated_config):
    cfg = configure_models_noninteractive(provider="openai", api_key="sk-x")
    assert (cfg.chat_provider, cfg.chat_model) == ("openai", "gpt-4o")  # recommended default
    assert cfg.embedding_provider == "disabled"
    assert cfg.embedding_model is None
    saved = json.loads(isolated_config.read_text(encoding="utf-8"))
    assert saved["openai_api_key"] == "sk-x"


def test_noninteractive_with_embeddings_fills_default_model(isolated_config):
    cfg = configure_models_noninteractive(provider="ollama", model="llama3", embedding_provider="ollama")
    assert cfg.chat_model == "llama3"
    assert cfg.embedding_provider == "ollama"
    assert cfg.embedding_model  # recommended default filled in


def test_noninteractive_no_embeddings_flag(isolated_config):
    cfg = configure_models_noninteractive(provider="claude", no_embeddings=True)
    assert cfg.chat_model == "claude-sonnet-4-6"
    assert cfg.embedding_provider == "disabled"


def test_noninteractive_unknown_provider_without_model_raises(isolated_config):
    with pytest.raises(ValueError):
        configure_models_noninteractive(provider="madeup")
