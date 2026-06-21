"""Provider factory selection + credential resolution (no network)."""

import json

import pytest
from yumi.core.features.config.credentials import (
    ensure_embedding_provider_supported,
    get_api_credentials,
)
from yumi.core.platform.providers import SUPPORTED_PROVIDERS, create_provider


@pytest.fixture
def isolated_config(monkeypatch, tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr("yumi.core.features.config.paths.CONFIG_PATH", p)
    monkeypatch.setattr("yumi.core.features.config.store.CONFIG_PATH", p)
    return p


# ── create_provider ──


def test_create_provider_ollama_needs_no_credentials():
    provider = create_provider("ollama")  # ollama is a core dependency
    assert type(provider).__name__ == "OllamaProvider"


def test_create_provider_unknown_raises():
    with pytest.raises(ValueError, match="Unknown provider"):
        create_provider("does-not-exist")


def test_supported_providers_listed():
    assert "ollama" in SUPPORTED_PROVIDERS
    assert "openai" in SUPPORTED_PROVIDERS


# ── credentials ──


def test_env_credentials_take_priority(isolated_config, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    creds = get_api_credentials()
    assert creds["openai_api_key"] == "env-key"


def test_credentials_fall_back_to_config(isolated_config, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    isolated_config.write_text(json.dumps({"gemini_api_key": "cfg-key"}), encoding="utf-8")
    creds = get_api_credentials()
    assert creds["gemini_api_key"] == "cfg-key"


@pytest.mark.parametrize("name", ["deepseek", "claude", "", "unknown"])
def test_embedding_provider_without_embedding_api_is_rejected(name):
    with pytest.raises(ValueError, match=repr(name)):
        ensure_embedding_provider_supported(name)


@pytest.mark.parametrize("name", ["ollama", "openai", "gemini", "disabled"])
def test_embedding_provider_supported_names_allowed(name):
    ensure_embedding_provider_supported(name)  # must not raise


def test_embedding_provider_disabled_not_allowed_when_embeddings_enabled():
    with pytest.raises(ValueError, match="disabled"):
        ensure_embedding_provider_supported("disabled", allow_disabled=False)
