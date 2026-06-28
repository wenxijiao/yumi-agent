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
        "XAI_API_KEY",
        "GROK_API_KEY",
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
    assert credentials.infer_chat_from_env() == ("openai", "gpt-5.5")


def test_infer_explicit_provider_beats_key(isolated_config):
    os.environ["OPENAI_API_KEY"] = "sk-test"
    os.environ["YUMI_CHAT_PROVIDER"] = "claude"
    assert credentials.infer_chat_from_env() == ("claude", "claude-opus-4-8")


def test_infer_from_xai_key(isolated_config):
    os.environ["XAI_API_KEY"] = "xai-test"
    assert credentials.infer_chat_from_env() == ("grok", "grok-4.3")


def test_infer_none_when_nothing_set(isolated_config):
    assert credentials.infer_chat_from_env() is None


# ── missing_credentials pre-flight ───────────────────────────────────────────


def test_missing_credentials_flags_cloud_chat_without_key(isolated_config):
    cfg = ModelConfig(chat_provider="gemini", chat_model="gemini-3.5-flash")
    issues = credentials.missing_credentials(cfg)
    chat = [i for i in issues if i["feature"] == "chat model"]
    assert chat == [
        {
            "feature": "chat model",
            "provider": "gemini",
            "env_var": "GEMINI_API_KEY",
            "config_field": "gemini_api_key",
            "fatal": True,
        }
    ]


def test_missing_credentials_satisfied_by_env(isolated_config):
    os.environ["GEMINI_API_KEY"] = "g-key"
    cfg = ModelConfig(chat_provider="gemini", chat_model="x")
    assert credentials.missing_credentials(cfg) == []


def test_missing_credentials_satisfied_by_config_field(isolated_config):
    cfg = ModelConfig(chat_provider="openai", chat_model="x", openai_api_key="sk-x")
    assert credentials.missing_credentials(cfg) == []


def test_missing_credentials_local_providers_never_flagged(isolated_config):
    cfg = ModelConfig(
        chat_provider="ollama",
        chat_model="m",
        embedding_provider="fastembed",
        embedding_model="e",
        stt_provider="whisper",
        stt_model="base",
        tts_provider="system",
    )
    assert credentials.missing_credentials(cfg) == []


def test_missing_credentials_flags_voice_features_non_fatal(isolated_config):
    cfg = ModelConfig(
        chat_provider="openai",
        chat_model="x",
        openai_api_key="sk-x",  # chat satisfied
        stt_provider="dashscope",
        stt_model="qwen3-asr-flash",
        tts_provider="dashscope",
        tts_voice="Cherry",
    )
    issues = credentials.missing_credentials(cfg)
    voice = {i["feature"]: i for i in issues}
    assert "chat model" not in voice  # chat key present
    assert voice["voice input (STT)"]["env_var"] == "DASHSCOPE_API_KEY"
    assert voice["voice input (STT)"]["fatal"] is False
    assert voice["spoken replies (TTS)"]["provider"] == "dashscope"


def test_ensure_chat_model_autodetects_and_persists(isolated_config):
    os.environ["GEMINI_API_KEY"] = "g-test"
    cfg = credentials.ensure_chat_model_configured(interactive=False)
    assert (cfg.chat_provider, cfg.chat_model) == ("gemini", "gemini-3.1-pro-preview")
    saved = json.loads(isolated_config.read_text(encoding="utf-8"))
    assert saved["chat_model"] == "gemini-3.1-pro-preview"


def test_ensure_chat_model_raises_without_anything(isolated_config):
    with pytest.raises(RuntimeError):
        credentials.ensure_chat_model_configured(interactive=False)


# ── non-interactive config ───────────────────────────────────────────────────


def test_noninteractive_cloud_defaults_embeddings_off(isolated_config):
    cfg = configure_models_noninteractive(provider="openai", api_key="sk-x")
    assert (cfg.chat_provider, cfg.chat_model) == ("openai", "gpt-5.5")  # non-interactive fallback
    assert cfg.embedding_provider == "disabled"
    assert cfg.embedding_model is None
    saved = json.loads(isolated_config.read_text(encoding="utf-8"))
    assert saved["openai_api_key"] == "sk-x"


def test_noninteractive_with_embeddings_fills_default_model(isolated_config):
    cfg = configure_models_noninteractive(provider="ollama", model="llama3", embedding_provider="ollama")
    assert cfg.chat_model == "llama3"
    assert cfg.embedding_provider == "ollama"
    assert cfg.embedding_model  # provider fallback filled in


def test_noninteractive_fastembed_fills_default_model(isolated_config):
    cfg = configure_models_noninteractive(provider="claude", embedding_provider="fastembed")
    assert cfg.embedding_provider == "fastembed"
    assert cfg.embedding_model == "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def test_noninteractive_no_embeddings_flag(isolated_config):
    cfg = configure_models_noninteractive(provider="claude", no_embeddings=True)
    assert cfg.chat_model == "claude-opus-4-8"
    assert cfg.embedding_provider == "disabled"


def test_noninteractive_deepseek_uses_v4_flash_default(isolated_config):
    cfg = configure_models_noninteractive(provider="deepseek", api_key="sk-deepseek")

    assert cfg.chat_model == "deepseek-v4-flash"
    assert cfg.embedding_provider == "disabled"


def test_noninteractive_grok_uses_grok_43_default(isolated_config):
    cfg = configure_models_noninteractive(provider="grok", api_key="xai-test")

    assert cfg.chat_model == "grok-4.3"
    assert cfg.embedding_provider == "disabled"


@pytest.mark.parametrize("embedding_provider", ["claude", "deepseek", "grok"])
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
    answers = iter(["4", "1"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    assert setup_wizard._choose_run_mode() == "cloud"


def test_choose_run_mode_can_exit(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt="": "3")

    assert setup_wizard._choose_run_mode() == "exit"


def test_configure_chat_model_exit_raises(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _prompt="": "3")

    with pytest.raises(SystemExit, match="Setup cancelled"):
        setup_wizard._configure_chat_model()


def test_select_page_aligns_all_text_to_content_column(monkeypatch, capsys):
    monkeypatch.setattr(setup_wizard, "_clear_screen", lambda: None)

    setup_wizard._draw_select_page(
        step="Step 1/5: AI model",
        title="How do you want to run the AI model?",
        message="No chat model is configured yet. Choose one to continue.",
        error="Ollama isn't reachable.\nDetails: missing service",
        options=[
            ("cloud", "Cloud API key", "quickest start"),
            ("local", "Local (Ollama)", "needs Ollama running"),
            ("exit", "Exit setup", ""),
        ],
        selected=1,
        footer="Use up/down to move. Press Enter to confirm.",
    )

    lines = [line for line in capsys.readouterr().out.splitlines() if line]

    # Header is a dot-rail + breadcrumb, not a boxed title with a gauge bar.
    assert any("Step 1 of 5" in line and "AI model" in line for line in lines)
    assert any("●" in line and "○" in line for line in lines)
    # Everything shares the single column-2 gutter ("  ").
    assert "  How do you want to run the AI model?" in lines
    assert "  ! Needs attention" in lines
    assert "  │ Ollama isn't reachable." in lines
    assert "  │ Details: missing service" in lines
    assert "  Use up/down to move. Press Enter to confirm." in lines
    # Options carry no number/">" — selection is the "▌" accent bar alone.
    assert "  Cloud API key" in lines
    assert "▌ Local (Ollama)" in lines
    assert "  Exit setup" in lines


def test_select_page_wraps_continuation_lines_to_content_column(monkeypatch, capsys):
    monkeypatch.setattr(setup_wizard, "_clear_screen", lambda: None)
    monkeypatch.setattr(setup_wizard, "_select_wrap_width", lambda _prefix: 42)

    setup_wizard._draw_select_page(
        step="Step 2/5: Memory (text embeddings)",
        title="Choose an embedding backend",
        message="Embeddings improve memory search and Edge tool routing.",
        warning=(
            "Important: keep the same embedding provider/model once Yumi starts saving memory. "
            "Changing it later can make old memory and tool-routing vectors inconsistent."
        ),
        options=[
            ("cloud", "Cloud embeddings", ""),
            (
                "local",
                "Local embeddings",
                "Yumi installs and downloads everything from the CLI before continuing",
            ),
        ],
        selected=0,
    )

    lines = [line for line in capsys.readouterr().out.splitlines() if line]

    # Notice body hangs off a "│" tick-bar on the gutter and wraps cleanly.
    assert "  ! Warning" in lines
    assert "  │ Important: keep the same embedding" in lines
    assert "  │ provider/model once Yumi starts saving" in lines
    assert "  │ memory. Changing it later can make old" in lines
    # Unselected option label at the gutter; description hangs at column 4.
    assert "  Local embeddings" in lines
    assert "    Yumi installs and downloads everything" in lines
    assert "    from the CLI before continuing" in lines
    assert all(not line.startswith("provider/model") for line in lines)
    assert all(not line.startswith("downloads everything") for line in lines)
    assert all(not line.startswith("continuing") for line in lines)


def test_back_options_do_not_include_descriptions(monkeypatch):
    captured_options = []

    def fake_select_option(**kwargs):
        captured_options.append(kwargs["options"])
        return "back"

    monkeypatch.setattr(setup_wizard, "_select_option", fake_select_option)

    assert setup_wizard._choose_cloud_provider() is None
    assert setup_wizard._choose_cloud_model("openai", "chat") is None

    back_options = [
        (label, description)
        for options in captured_options
        for _value, label, description in options
        if label == "Back"
    ]
    assert back_options
    assert all(description == "" for _label, description in back_options)


def test_cloud_model_quick_choices_do_not_include_descriptions(monkeypatch):
    captured_options = []

    def fake_select_option(**kwargs):
        captured_options.append(kwargs["options"])
        return "back"

    monkeypatch.setattr(setup_wizard, "_select_option", fake_select_option)

    assert setup_wizard._choose_cloud_model("openai", "chat") is None

    model_options = [
        (value, label, description) for value, label, description in captured_options[0] if value.startswith("gpt-")
    ]
    assert [value for value, _label, _description in model_options] == ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini"]
    assert all(description == "" for _value, _label, description in model_options)


def test_configure_chat_model_cloud_uses_quick_model_choice(isolated_config, monkeypatch):
    answers = iter(["1", "1", "sk-test", "1"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    monkeypatch.setattr(setup_wizard, "ensure_provider_available", lambda provider: None)

    provider, model = setup_wizard._configure_chat_model()

    assert (provider, model) == ("openai", "gpt-5.5")
    assert os.environ["OPENAI_API_KEY"] == "sk-test"


def test_chat_action_requires_config_when_missing():
    assert setup_wizard._choose_chat_action(ModelConfig()) == "reconfigure"


def test_chat_action_can_keep_available_current(monkeypatch):
    cfg = ModelConfig(chat_provider="openai", chat_model="gpt-5.5")
    monkeypatch.setattr(setup_wizard, "ensure_provider_available", lambda provider: None)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")

    assert setup_wizard._choose_chat_action(cfg) == "keep"


def test_chat_action_reconfigures_unavailable_current(monkeypatch):
    cfg = ModelConfig(chat_provider="openai", chat_model="gpt-5.5")

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


def test_embedding_action_requires_config_when_missing(monkeypatch):
    def fail_select_option(**_kwargs):
        pytest.fail("missing embeddings should not render a keep-current menu")

    monkeypatch.setattr(setup_wizard, "_select_option", fail_select_option)

    assert setup_wizard._choose_embedding_action(ModelConfig(embedding_provider="disabled", embedding_model=None)) == (
        "reconfigure"
    )


def test_configure_embeddings_shows_stability_warning(monkeypatch):
    captured = []

    def fake_select_option(**kwargs):
        captured.append(kwargs)
        return "skip"

    monkeypatch.setattr(setup_wizard, "_select_option", fake_select_option)
    cfg = ModelConfig(chat_provider="openai", chat_model="m")

    setup_wizard._configure_embeddings(cfg, "openai")

    assert "keep the same embedding provider/model" in captured[0]["warning"]
    assert "yumi --cleanup-memory" in captured[0]["warning"]
    assert cfg.embedding_provider == "disabled"


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
    cleared: list[bool] = []

    class FakeFastEmbedProvider:
        def pull_model(self, model: str) -> None:
            pulled.append(model)

    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))
    monkeypatch.setattr("yumi.core.features.config.feature_install.ensure_feature_installed", lambda *a, **k: True)
    monkeypatch.setattr(setup_wizard, "_get_provider", lambda provider: FakeFastEmbedProvider())
    monkeypatch.setattr(setup_wizard, "_clear_screen", lambda: cleared.append(True))

    setup_wizard._setup_embeddings(cfg, "claude")

    assert cfg.embedding_provider == "fastembed"
    assert cfg.embedding_model == "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    assert pulled == [cfg.embedding_model]
    assert cleared == [True]


def test_setup_ollama_embeddings_manual_clears_download_progress(monkeypatch):
    choices = iter(["manual"])
    cleared: list[bool] = []
    prepared: list[str] = []

    def fake_select_option(**_kwargs):
        return next(choices)

    def fake_ensure_model_ready(provider: str, model_name: str) -> str:
        prepared.append(f"{provider}:{model_name}")
        return model_name

    cfg = ModelConfig(chat_provider="openai", chat_model="m")
    monkeypatch.setattr(setup_wizard, "_select_option", fake_select_option)
    monkeypatch.setattr("builtins.input", lambda _prompt="": "qwen3-embedding:0.6b")
    monkeypatch.setattr(setup_wizard, "ensure_provider_available", lambda provider: None)
    monkeypatch.setattr(setup_wizard, "ensure_model_ready", fake_ensure_model_ready)
    monkeypatch.setattr(setup_wizard, "_clear_screen", lambda: cleared.append(True))

    assert setup_wizard._setup_ollama_embeddings(cfg) is True

    assert cfg.embedding_provider == "ollama"
    assert cfg.embedding_model == "qwen3-embedding:0.6b"
    assert prepared == ["ollama:qwen3-embedding:0.6b"]
    assert cleared == [True]


def test_setup_ollama_embeddings_reports_missing_installed_models(monkeypatch):
    choices = iter(["installed", "back"])
    captured = []

    class FakeOllamaProvider:
        def list_models(self) -> list[str]:
            return []

    def fake_select_option(**kwargs):
        captured.append(kwargs)
        return next(choices)

    cfg = ModelConfig(chat_provider="openai", chat_model="m")
    monkeypatch.setattr(setup_wizard, "_select_option", fake_select_option)
    monkeypatch.setattr(setup_wizard, "ensure_provider_available", lambda provider: None)
    monkeypatch.setattr(setup_wizard, "_get_provider", lambda provider: FakeOllamaProvider())

    assert setup_wizard._setup_ollama_embeddings(cfg) is False

    assert captured[0]["error"] is None
    assert "No installed Ollama embedding models were found" in captured[1]["error"]
    assert cfg.embedding_model is None


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


def test_prompt_stt_config_hides_keep_when_unconfigured(monkeypatch):
    captured = []

    def fake_select_option(**kwargs):
        captured.append(kwargs)
        return "disable"

    cfg = ModelConfig(stt_provider="disabled", stt_model=None)
    monkeypatch.setattr(setup_wizard, "_select_option", fake_select_option)

    setup_wizard._prompt_stt_config(cfg)

    values = [value for value, _label, _description in captured[0]["options"]]
    assert "keep" not in values  # nothing to keep on a first run
    assert values == ["cloud", "local", "disable", "back"]


def test_prompt_stt_config_offers_keep_when_configured(monkeypatch):
    captured = []

    def fake_select_option(**kwargs):
        captured.append(kwargs)
        return "keep"

    cfg = ModelConfig(stt_provider="whisper", stt_model="base")
    monkeypatch.setattr(setup_wizard, "_select_option", fake_select_option)

    assert setup_wizard._prompt_stt_config(cfg) == "next"

    values = [value for value, _label, _description in captured[0]["options"]]
    assert values == ["keep", "cloud", "local", "disable", "back"]


def test_prompt_stt_config_cloud_picks_provider_then_model(isolated_config, monkeypatch):
    isolated_config.write_text(json.dumps({"gemini_api_key": "g-existing"}), encoding="utf-8")
    # top menu → cloud, provider → gemini, model → gemini-2.5-flash
    selections = iter(["cloud", "gemini", "gemini-2.5-flash"])
    cfg = ModelConfig()
    monkeypatch.setattr(setup_wizard, "_select_option", lambda **_k: next(selections))
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")  # reuse the saved key

    assert setup_wizard._prompt_stt_config(cfg) == "next"

    assert cfg.stt_provider == "gemini"
    assert cfg.stt_backend == "api"
    assert cfg.stt_model == "gemini-2.5-flash"
    assert cfg.stt_model_dir is None


def test_prompt_stt_config_cloud_grok_without_model(isolated_config, monkeypatch):
    isolated_config.write_text(json.dumps({"grok_api_key": "xai-existing"}), encoding="utf-8")
    selections = iter(["cloud", "grok"])
    cfg = ModelConfig()
    monkeypatch.setattr(setup_wizard, "_select_option", lambda **_k: next(selections))
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")

    assert setup_wizard._prompt_stt_config(cfg) == "next"

    assert cfg.stt_provider == "grok"
    assert cfg.stt_backend == "api"
    assert cfg.stt_model is None
    assert cfg.stt_model_dir is None


def test_prompt_stt_config_local_whisper_caches_model(monkeypatch):
    selections = iter(["local", "small"])  # top menu → local, then a Whisper model
    captured = []
    installed_features = []

    def fake_select_option(**kwargs):
        captured.append(kwargs)
        return next(selections)

    def fake_ensure_feature_installed(feature, *, assume_yes=False):
        installed_features.append((feature, assume_yes))
        return False

    cfg = ModelConfig()
    monkeypatch.setattr(setup_wizard, "_select_option", fake_select_option)
    monkeypatch.setattr("builtins.input", lambda _prompt="": pytest.fail("STT setup should not ask for a cache path"))
    monkeypatch.setattr(
        "yumi.core.features.config.feature_install.ensure_feature_installed", fake_ensure_feature_installed
    )

    setup_wizard._prompt_stt_config(cfg)

    # The Whisper-model menu lists the bare models (no "(default)" recommendation).
    whisper_values = [value for value, _label, _description in captured[1]["options"] if value != "back"]
    assert whisper_values == list(setup_wizard._WHISPER_MODELS)
    assert cfg.stt_provider == "whisper"
    assert cfg.stt_model == "small"
    assert cfg.stt_model_dir == str(setup_wizard._DEFAULT_WHISPER_MODEL_DIR)
    assert installed_features == [("stt", True)]


def test_prompt_tts_config_top_menu_is_cloud_local(monkeypatch):
    captured = []

    def fake_select_option(**kwargs):
        captured.append(kwargs)
        return "disable"

    cfg = ModelConfig()
    monkeypatch.setattr(setup_wizard, "_select_option", fake_select_option)

    setup_wizard._prompt_tts_config(cfg)

    values = [value for value, _label, _description in captured[0]["options"]]
    # No "keep" on a first run; system/dashscope/qwen are nested under cloud/local.
    assert values == ["cloud", "local", "disable", "back"]
    assert all(value not in ("system", "dashscope", "qwen") for value, _l, _d in captured[0]["options"])


def test_prompt_tts_config_offers_keep_when_configured(monkeypatch):
    captured = []

    def fake_select_option(**kwargs):
        captured.append(kwargs)
        return "keep"

    cfg = ModelConfig(tts_provider="system")
    monkeypatch.setattr(setup_wizard, "_select_option", fake_select_option)

    assert setup_wizard._prompt_tts_config(cfg) == "next"

    values = [value for value, _label, _description in captured[0]["options"]]
    assert values == ["keep", "cloud", "local", "disable", "back"]


def test_prompt_tts_config_local_system_voice_does_not_prompt(monkeypatch):
    selections = iter(["local", "system"])  # top menu → local, then system voice
    monkeypatch.setattr(setup_wizard, "_select_option", lambda **_k: next(selections))
    monkeypatch.setattr("builtins.input", lambda _prompt="": pytest.fail("TTS setup should not ask to test playback"))

    cfg = ModelConfig()
    setup_wizard._prompt_tts_config(cfg)

    assert cfg.tts_provider == "system"


def test_prompt_tts_config_cloud_dashscope_installs(isolated_config, monkeypatch):
    selections = iter(["cloud", "dashscope", "Cherry"])  # cloud → dashscope → voice
    installed_features = []

    def fake_ensure_feature_installed(feature, *, assume_yes=False):
        installed_features.append((feature, assume_yes))
        return False

    cfg = ModelConfig(tts_api_key="dashscope-key")  # key already saved → no prompt
    monkeypatch.setattr(setup_wizard, "_select_option", lambda **_k: next(selections))
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")  # reuse saved DashScope key
    monkeypatch.setattr(
        "yumi.core.features.config.feature_install.ensure_feature_installed", fake_ensure_feature_installed
    )

    setup_wizard._prompt_tts_config(cfg)

    assert cfg.tts_provider == "dashscope"
    assert cfg.tts_voice == "Cherry"
    assert installed_features == [("tts", True)]


def test_prompt_tts_config_cloud_grok(isolated_config, monkeypatch):
    isolated_config.write_text(json.dumps({"grok_api_key": "xai-existing"}), encoding="utf-8")
    selections = iter(["cloud", "grok", "ara"])

    cfg = ModelConfig()
    monkeypatch.setattr(setup_wizard, "_select_option", lambda **_k: next(selections))
    monkeypatch.setattr("builtins.input", lambda _prompt="": "")

    assert setup_wizard._prompt_tts_config(cfg) == "next"

    assert cfg.tts_provider == "grok"
    assert cfg.tts_model is None
    assert cfg.tts_voice == "ara"
    assert cfg.tts_language == "auto"


def test_run_model_setup_saves_chat_before_optional_steps(isolated_config, monkeypatch):
    monkeypatch.setattr(setup_wizard, "_configure_chat_model", lambda: ("deepseek", "deepseek-v4-flash"))

    def stop_after_chat(_config: ModelConfig, _chat_provider: str) -> None:
        raise RuntimeError("stop after chat")

    monkeypatch.setattr(setup_wizard, "_setup_embeddings", stop_after_chat)

    with pytest.raises(RuntimeError, match="stop after chat"):
        setup_wizard.run_model_setup(force=True)

    saved = json.loads(isolated_config.read_text(encoding="utf-8"))
    assert saved["chat_provider"] == "deepseek"
    assert saved["chat_model"] == "deepseek-v4-flash"


def test_run_model_setup_saves_embeddings_before_voice_step(isolated_config, monkeypatch):
    isolated_config.write_text(
        json.dumps({"chat_provider": "openai", "chat_model": "gpt-5.5"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(setup_wizard, "_choose_chat_action", lambda _current: "keep")

    def configure_embeddings(config: ModelConfig, _chat_provider: str) -> None:
        config.embedding_provider = "fastembed"
        config.embedding_model = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

    def stop_after_embeddings(_config: ModelConfig) -> None:
        raise RuntimeError("stop after embeddings")

    monkeypatch.setattr(setup_wizard, "_setup_embeddings", configure_embeddings)
    monkeypatch.setattr(setup_wizard, "_prompt_stt_config", stop_after_embeddings)

    with pytest.raises(RuntimeError, match="stop after embeddings"):
        setup_wizard.run_model_setup(force=True)

    saved = json.loads(isolated_config.read_text(encoding="utf-8"))
    assert saved["embedding_provider"] == "fastembed"
    assert saved["embedding_model"] == "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def test_run_model_setup_back_revisits_previous_step(isolated_config, monkeypatch):
    """A 'back' from a step re-runs the previous step instead of forcing a re-run."""
    isolated_config.write_text(json.dumps({"chat_provider": "openai", "chat_model": "gpt-5.5"}), encoding="utf-8")
    monkeypatch.setattr(setup_wizard, "_interactive_terminal", lambda: True)
    monkeypatch.setattr(setup_wizard, "_clear_screen", lambda: None)
    monkeypatch.setattr(setup_wizard, "_render_setup_summary", lambda _config: None)
    monkeypatch.setattr(setup_wizard, "_choose_chat_action", lambda _current: "keep")

    calls: list[str] = []
    stt_results = iter(["back", "next"])  # first STT visit goes back to embeddings
    monkeypatch.setattr(setup_wizard, "_setup_embeddings", lambda _c, _p: calls.append("emb") or "next")
    monkeypatch.setattr(setup_wizard, "_prompt_stt_config", lambda _c: calls.append("stt") or next(stt_results))
    monkeypatch.setattr(setup_wizard, "_prompt_tts_config", lambda _c: calls.append("tts") or "next")

    setup_wizard.run_model_setup(force=True)

    assert calls == ["emb", "stt", "emb", "stt", "tts"]


def test_run_model_setup_exit_from_keep_menu_cancels(isolated_config, monkeypatch):
    isolated_config.write_text(json.dumps({"chat_provider": "openai", "chat_model": "gpt-5.5"}), encoding="utf-8")
    monkeypatch.setattr(setup_wizard, "_interactive_terminal", lambda: True)
    monkeypatch.setattr(setup_wizard, "_clear_screen", lambda: None)
    monkeypatch.setattr(setup_wizard, "_choose_chat_action", lambda _current: "exit")

    with pytest.raises(SystemExit):
        setup_wizard.run_model_setup(force=True)


def test_run_model_setup_preserves_provider_api_key(isolated_config, monkeypatch):
    """A cloud key saved during the chat step must survive the per-step saves.

    Regression: the driver's long-lived config object was stale w.r.t. the key
    that `_persist_cloud_api_key` wrote to disk, so the next save overwrote it —
    a key entered during setup then vanished (server: 'API key is required').
    """
    monkeypatch.setattr(setup_wizard, "_interactive_terminal", lambda: True)
    monkeypatch.setattr(setup_wizard, "_clear_screen", lambda: None)
    monkeypatch.setattr(setup_wizard, "_render_setup_summary", lambda _config: None)
    monkeypatch.setattr(setup_wizard, "_choose_chat_action", lambda _current: "reconfigure")

    def fake_configure_chat_model():
        setup_wizard._persist_cloud_api_key("gemini", "g-secret", announce=False)
        return ("gemini", "gemini-3.5-flash")

    monkeypatch.setattr(setup_wizard, "_configure_chat_model", fake_configure_chat_model)
    monkeypatch.setattr(setup_wizard, "_setup_embeddings", lambda _c, _p: "next")
    monkeypatch.setattr(setup_wizard, "_prompt_stt_config", lambda _c: "next")
    monkeypatch.setattr(setup_wizard, "_prompt_tts_config", lambda _c: "next")

    setup_wizard.run_model_setup(force=True)

    saved = json.loads(isolated_config.read_text(encoding="utf-8"))
    assert saved["chat_provider"] == "gemini"
    assert saved["chat_model"] == "gemini-3.5-flash"
    assert saved["gemini_api_key"] == "g-secret"


def test_run_model_setup_preserves_messaging_token(isolated_config, monkeypatch):
    """A bridge token saved by the Step 5 messaging callback must survive the
    wizard's per-step save.

    Regression: messaging save_* helpers write to a freshly-loaded config, so the
    driver's long-lived config object stayed stale (token=None) and the post-step
    save_model_config wiped the token the user just entered.
    """
    from yumi.core.features.config.telegram import save_telegram_bot_token

    isolated_config.write_text(
        json.dumps({"chat_provider": "openai", "chat_model": "gpt-5.5"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(setup_wizard, "_interactive_terminal", lambda: True)
    monkeypatch.setattr(setup_wizard, "_clear_screen", lambda: None)
    monkeypatch.setattr(setup_wizard, "_render_setup_summary", lambda _config: None)
    monkeypatch.setattr(setup_wizard, "_choose_chat_action", lambda _current: "keep")
    monkeypatch.setattr(setup_wizard, "_setup_embeddings", lambda _c, _p: "next")
    monkeypatch.setattr(setup_wizard, "_prompt_stt_config", lambda _c: "next")
    monkeypatch.setattr(setup_wizard, "_prompt_tts_config", lambda _c: "next")

    def fake_messaging():
        save_telegram_bot_token("tg-secret")

    setup_wizard.run_model_setup(force=True, messaging=fake_messaging)

    saved = json.loads(isolated_config.read_text(encoding="utf-8"))
    assert saved["telegram_bot_token"] == "tg-secret"
    # The chat config the user kept must still be intact alongside the token.
    assert saved["chat_provider"] == "openai"


def test_framed_prompt_eof_cancels_cleanly(monkeypatch):
    """Non-interactive _framed_prompt on closed stdin cancels via SystemExit
    instead of letting an EOFError traceback escape (CI / Docker / `</dev/null`)."""
    monkeypatch.setattr(setup_wizard, "_interactive_terminal", lambda: False)

    def _raise_eof(_prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", _raise_eof)
    with pytest.raises(SystemExit):
        setup_wizard._framed_prompt("OpenAI API key", secret=True)
