"""Setup-flow behaviour: optional embeddings, env auto-detect, non-interactive config.

These cover the cloud-first / local-optional setup rework: a chat model can be
inferred from a bare API key (Docker-friendly), embeddings default to off, and
`yumi --setup --provider ...` configures everything without prompts.
"""

import json
import os

import pytest
from yumi.core.features.config import configure_models_noninteractive, credentials, setup_wizard
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
        "YUMI_EMBEDDING_PROVIDER",
        "YUMI_EMBED_MODEL",
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


def test_noninteractive_fastembed_fills_default_model(isolated_config):
    cfg = configure_models_noninteractive(provider="claude", embedding_provider="fastembed")
    assert cfg.embedding_provider == "fastembed"
    assert cfg.embedding_model == "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def test_noninteractive_no_embeddings_flag(isolated_config):
    cfg = configure_models_noninteractive(provider="claude", no_embeddings=True)
    assert cfg.chat_model == "claude-sonnet-4-6"
    assert cfg.embedding_provider == "disabled"


@pytest.mark.parametrize("embedding_provider", ["claude", "deepseek"])
def test_noninteractive_rejects_providers_without_embedding_api(isolated_config, embedding_provider):
    with pytest.raises(ValueError, match=embedding_provider):
        configure_models_noninteractive(
            provider="ollama",
            model="llama3",
            embedding_provider=embedding_provider,
        )


def test_noninteractive_unknown_provider_without_model_raises(isolated_config):
    with pytest.raises(ValueError):
        configure_models_noninteractive(provider="madeup")


def test_noninteractive_unknown_provider_with_model_raises(isolated_config):
    with pytest.raises(ValueError, match="Unknown chat provider"):
        configure_models_noninteractive(provider="madeup", model="some-model")


def test_choose_run_mode_does_not_offer_skip(monkeypatch):
    answers = iter(["3", "1"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    assert setup_wizard._choose_run_mode() == "cloud"


def test_configure_chat_model_cloud_uses_curated_default(isolated_config, monkeypatch):
    answers = iter(["1", "1", "sk-test", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    monkeypatch.setattr(setup_wizard, "ensure_provider_available", lambda provider: None)

    provider, model = setup_wizard._configure_chat_model()

    assert (provider, model) == ("openai", "gpt-4o")
    assert os.environ["OPENAI_API_KEY"] == "sk-test"


def test_chat_action_requires_config_when_missing():
    assert setup_wizard._choose_chat_action(ModelConfig()) == "reconfigure"


def test_chat_action_can_keep_available_current(monkeypatch):
    cfg = ModelConfig(chat_provider="openai", chat_model="gpt-4o")
    monkeypatch.setattr(setup_wizard, "ensure_provider_available", lambda provider: None)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")

    assert setup_wizard._choose_chat_action(cfg) == "keep"


def test_chat_action_reconfigures_unavailable_current(monkeypatch):
    cfg = ModelConfig(chat_provider="openai", chat_model="gpt-4o")

    def _fail(_provider: str) -> None:
        raise RuntimeError("missing key")

    monkeypatch.setattr(setup_wizard, "ensure_provider_available", _fail)

    assert setup_wizard._choose_chat_action(cfg) == "reconfigure"


def test_setup_embeddings_cloud_reuses_existing_key(isolated_config, monkeypatch):
    isolated_config.write_text(json.dumps({"openai_api_key": "sk-existing-key"}), encoding="utf-8")
    cfg = ModelConfig(chat_provider="claude", chat_model="m")
    answers = iter(["1", "1", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    setup_wizard._setup_embeddings(cfg, "claude")

    assert cfg.embedding_provider == "openai"
    assert cfg.embedding_model == "text-embedding-3-small"
    assert os.environ["OPENAI_API_KEY"] == "sk-existing-key"


def test_setup_embeddings_keep_available_current(monkeypatch):
    cfg = ModelConfig(
        chat_provider="claude",
        chat_model="m",
        embedding_provider="fastembed",
        embedding_model="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    )
    monkeypatch.setattr(setup_wizard, "ensure_provider_available", lambda provider: None)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")

    setup_wizard._setup_embeddings(cfg, "claude")

    assert cfg.embedding_provider == "fastembed"
    assert cfg.embedding_model == "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def test_setup_embeddings_unavailable_current_can_skip(monkeypatch):
    cfg = ModelConfig(
        chat_provider="claude",
        chat_model="m",
        embedding_provider="fastembed",
        embedding_model="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    )

    def _fail(_provider: str) -> None:
        raise RuntimeError("missing fastembed")

    monkeypatch.setattr(setup_wizard, "ensure_provider_available", _fail)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "4")

    setup_wizard._setup_embeddings(cfg, "claude")

    assert cfg.embedding_provider == "disabled"
    assert cfg.embedding_model is None


def test_setup_embeddings_local_prepares_fastembed(isolated_config, monkeypatch):
    cfg = ModelConfig(chat_provider="claude", chat_model="m")
    answers = iter(["2", "1"])
    pulled: list[str] = []

    class FakeFastEmbedProvider:
        def pull_model(self, model: str) -> None:
            pulled.append(model)

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    monkeypatch.setattr("yumi.core.features.config.feature_install.ensure_feature_installed", lambda *a, **k: True)
    monkeypatch.setattr(setup_wizard, "_get_provider", lambda provider: FakeFastEmbedProvider())

    setup_wizard._setup_embeddings(cfg, "claude")

    assert cfg.embedding_provider == "fastembed"
    assert cfg.embedding_model == "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    assert pulled == [cfg.embedding_model]


def test_setup_embeddings_ollama_uses_installed_model(isolated_config, monkeypatch):
    cfg = ModelConfig(chat_provider="openai", chat_model="m")
    answers = iter(["3", "1", "2"])

    class FakeOllamaProvider:
        def list_models(self) -> list[str]:
            return ["chat-model", "my-embed-model"]

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    monkeypatch.setattr(setup_wizard, "ensure_provider_available", lambda provider: None)
    monkeypatch.setattr(setup_wizard, "_get_provider", lambda provider: FakeOllamaProvider())

    setup_wizard._setup_embeddings(cfg, "openai")

    assert cfg.embedding_provider == "ollama"
    assert cfg.embedding_model == "my-embed-model"
