"""Default model config values (no network, no server)."""

import json

from yumi.core.features.config import ModelConfig
from yumi.core.features.config.store import ensure_full_model_config_file, load_model_config


def test_model_config_default_provider():
    cfg = ModelConfig()
    assert cfg.chat_provider == "ollama"
    assert cfg.embedding_provider == "ollama"
    assert cfg.chat_append_current_time is True
    assert cfg.chat_append_tool_use_instruction is True
    assert cfg.edge_tools_enable_dynamic_routing is True
    assert cfg.edge_tools_retrieval_limit == 20
    assert cfg.stt_provider == "disabled"
    assert cfg.stt_backend == "faster-whisper"
    assert cfg.stt_model is None
    assert cfg.stt_language == "auto"


def test_model_config_stt_env_overrides(monkeypatch, tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"chat_model": "m"}), encoding="utf-8")
    monkeypatch.setattr("yumi.core.features.config.paths.CONFIG_PATH", p)
    monkeypatch.setattr("yumi.core.features.config.store.CONFIG_PATH", p)
    monkeypatch.setenv("YUMI_STT_PROVIDER", "whisper")
    monkeypatch.setenv("YUMI_STT_BACKEND", "faster-whisper")
    monkeypatch.setenv("YUMI_STT_MODEL", "small")
    monkeypatch.setenv("YUMI_STT_MODEL_DIR", "/tmp/yumi-whisper")
    monkeypatch.setenv("YUMI_STT_LANGUAGE", "auto")

    cfg = load_model_config()

    assert cfg.stt_provider == "whisper"
    assert cfg.stt_backend == "faster-whisper"
    assert cfg.stt_model == "small"
    assert cfg.stt_model_dir == "/tmp/yumi-whisper"
    assert cfg.stt_language == "auto"


def test_model_config_migrates_legacy_proactive_timezone_json_key():
    cfg = ModelConfig.model_validate({"proactive_quiet_hours_timezone": "Pacific/Auckland"})
    assert cfg.local_timezone == "Pacific/Auckland"


def test_model_config_local_timezone_wins_over_legacy_key_in_json():
    cfg = ModelConfig.model_validate(
        {
            "local_timezone": "Europe/London",
            "proactive_quiet_hours_timezone": "Pacific/Auckland",
        }
    )
    assert cfg.local_timezone == "Europe/London"


def test_model_config_explicit_proactive_mode_overrides_legacy_enabled():
    cfg = ModelConfig.model_validate({"proactive_enabled": True, "proactive_mode": "off"})
    assert cfg.proactive_mode == "off"
    assert cfg.proactive_enabled is False


def test_full_config_file_writes_all_default_keys(monkeypatch, tmp_path):
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"chat_model": "m"}), encoding="utf-8")
    monkeypatch.setattr("yumi.core.features.config.paths.CONFIG_PATH", p)
    monkeypatch.setattr("yumi.core.features.config.store.CONFIG_PATH", p)

    cfg = ensure_full_model_config_file()
    saved = json.loads(p.read_text(encoding="utf-8"))

    assert cfg.chat_model == "m"
    assert saved["chat_model"] == "m"
    assert saved["proactive_mode"] == "off"
    assert saved["proactive_enabled"] is False
    assert saved.get("proactive_schedule_times") == []
    assert saved.get("proactive_schedule_interval_minutes") is None
    assert saved.get("proactive_schedule_require_idle") is True
    assert saved["proactive_check_interval_seconds"] == 900
    assert saved["local_timezone"] is None
    assert saved["proactive_check_interval_jitter_ratio"] == 0.15
    assert saved["proactive_unreplied_escalation_jitter_ratio"] == 0.0
    assert saved["proactive_check_in_probability"] == 0.35
    assert saved["telegram_bot_token"] is None
