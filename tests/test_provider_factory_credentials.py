"""Provider factory selection + credential resolution (no network)."""

import json
import sys
import types
import warnings

import pytest
from yumi.core.features.config.credentials import (
    ensure_embedding_provider_supported,
    ensure_model_ready,
    ensure_provider_available,
    get_api_credentials,
)
from yumi.core.platform.exceptions import ProviderNotReadyError
from yumi.core.platform.providers import EMBEDDING_ONLY_PROVIDERS, SUPPORTED_PROVIDERS, create_provider


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
    assert "grok" in SUPPORTED_PROVIDERS
    assert "fastembed" in EMBEDDING_ONLY_PROVIDERS


def test_create_provider_fastembed_is_embedding_only():
    provider = create_provider("fastembed")
    assert type(provider).__name__ == "FastEmbedProvider"


def test_fastembed_provider_suppresses_known_pooling_warning(monkeypatch):
    from yumi.core.platform.providers.fastembed_provider import FastEmbedProvider

    class FakeTextEmbedding:
        def __init__(self, model_name: str) -> None:
            warnings.warn(
                f"The model {model_name} now uses mean pooling instead of CLS embedding. "
                "In order to preserve the previous behaviour, consider pinning fastembed.",
                UserWarning,
                stacklevel=1,
            )

        def embed(self, _texts):
            return [[1.0, 2.0]]

    fake_fastembed = types.ModuleType("fastembed")
    fake_fastembed.TextEmbedding = FakeTextEmbedding
    monkeypatch.setitem(sys.modules, "fastembed", fake_fastembed)

    provider = FastEmbedProvider()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert provider.embed("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "hello") == [1.0, 2.0]

    assert caught == []


def test_fastembed_provider_uses_yumi_cache_dir(monkeypatch, tmp_path):
    from yumi.core.platform.providers import fastembed_provider
    from yumi.core.platform.providers.fastembed_provider import FastEmbedProvider

    captured = {}

    class FakeTextEmbedding:
        def __init__(self, model_name: str, cache_dir: str | None = None) -> None:
            captured.update(model_name=model_name, cache_dir=cache_dir)

        def embed(self, _texts):
            return [[1.0, 2.0]]

    fake_fastembed = types.ModuleType("fastembed")
    fake_fastembed.TextEmbedding = FakeTextEmbedding
    cache_dir = tmp_path / "fastembed"
    monkeypatch.setitem(sys.modules, "fastembed", fake_fastembed)
    monkeypatch.setattr(fastembed_provider, "FASTEMBED_MODELS_DIR", cache_dir)

    provider = FastEmbedProvider()
    assert provider.embed("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "hello") == [1.0, 2.0]

    assert captured == {
        "model_name": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "cache_dir": str(cache_dir),
    }
    assert cache_dir.exists()


def test_ensure_model_ready_pulls_fastembed(monkeypatch):
    pulled: list[str] = []

    class FakeProvider:
        def pull_model(self, model: str) -> None:
            pulled.append(model)

    monkeypatch.setattr("yumi.core.features.config.credentials._get_provider", lambda provider: FakeProvider())

    assert ensure_model_ready("fastembed", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2") == (
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )
    assert pulled == ["sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"]


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


def test_xai_credentials_take_priority(isolated_config, monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "xai-env")
    creds = get_api_credentials()
    assert creds["grok_api_key"] == "xai-env"


@pytest.mark.parametrize("name", ["deepseek", "claude", "grok", "", "unknown"])
def test_embedding_provider_without_embedding_api_is_rejected(name):
    with pytest.raises(ValueError, match=repr(name)):
        ensure_embedding_provider_supported(name)


@pytest.mark.parametrize("name", ["ollama", "openai", "gemini", "fastembed", "disabled"])
def test_embedding_provider_supported_names_allowed(name):
    ensure_embedding_provider_supported(name)  # must not raise


def test_embedding_provider_disabled_not_allowed_when_embeddings_enabled():
    with pytest.raises(ValueError, match="disabled"):
        ensure_embedding_provider_supported("disabled", allow_disabled=False)


def test_fastembed_readiness_reports_missing_package(monkeypatch):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None if name == "fastembed" else object())
    with pytest.raises(ProviderNotReadyError, match="FastEmbed"):
        ensure_provider_available("fastembed")
