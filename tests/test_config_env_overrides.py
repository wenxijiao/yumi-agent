"""Cover the KUMI_*/TELEGRAM_*/LINE_* environment overrides in load_model_config.

The override block is large pure logic (parse + clamp + fallback). These tests
exercise the value paths, the clamping bounds, and the parse-failure fallbacks
that were previously untested.
"""

import json

import pytest
from kumi.core.features.config.store import load_model_config


@pytest.fixture
def isolated_config(monkeypatch, tmp_path):
    """Point config at an empty file so only env overrides apply."""
    p = tmp_path / "config.json"
    p.write_text(json.dumps({}), encoding="utf-8")
    monkeypatch.setattr("kumi.core.features.config.paths.CONFIG_PATH", p)
    monkeypatch.setattr("kumi.core.features.config.store.CONFIG_PATH", p)
    return p


def test_chat_and_embedding_overrides(isolated_config, monkeypatch):
    monkeypatch.setenv("KUMI_CHAT_PROVIDER", "openai")
    monkeypatch.setenv("KUMI_CHAT_MODEL", "gpt-x")
    monkeypatch.setenv("KUMI_EMBEDDING_PROVIDER", "gemini")
    monkeypatch.setenv("KUMI_EMBED_MODEL", "embed-1")
    cfg = load_model_config()
    assert cfg.chat_provider == "openai"
    assert cfg.chat_model == "gpt-x"
    assert cfg.embedding_provider == "gemini"
    assert cfg.embedding_model == "embed-1"


def test_memory_limits_are_clamped(isolated_config, monkeypatch):
    monkeypatch.setenv("KUMI_MEMORY_MAX_RECENT", "9999")  # clamp to 500
    monkeypatch.setenv("KUMI_MEMORY_MAX_RELATED", "-5")  # clamp to 0
    cfg = load_model_config()
    assert cfg.memory_max_recent_messages == 500
    assert cfg.memory_max_related_messages == 0


def test_memory_limit_invalid_value_is_ignored(isolated_config, monkeypatch):
    default = load_model_config().memory_max_recent_messages
    monkeypatch.setenv("KUMI_MEMORY_MAX_RECENT", "not-a-number")
    cfg = load_model_config()
    assert cfg.memory_max_recent_messages == default  # ValueError -> keep default


@pytest.mark.parametrize(
    "raw,expected",
    [("1", True), ("true", True), ("on", True), ("0", False), ("no", False), ("off", False)],
)
def test_env_bool_parsing(isolated_config, monkeypatch, raw, expected):
    monkeypatch.setenv("KUMI_CHAT_APPEND_CURRENT_TIME", raw)
    assert load_model_config().chat_append_current_time is expected


def test_proactive_mode_valid_and_invalid(isolated_config, monkeypatch):
    monkeypatch.setenv("KUMI_PROACTIVE_MODE", "scheduled")
    assert load_model_config().proactive_mode == "scheduled"
    monkeypatch.setenv("KUMI_PROACTIVE_MODE", "bogus")  # ignored
    assert load_model_config().proactive_mode != "bogus"


def test_proactive_enabled_derives_mode(isolated_config, monkeypatch):
    monkeypatch.setenv("KUMI_PROACTIVE_ENABLED", "true")
    cfg = load_model_config()
    assert cfg.proactive_enabled is True
    assert cfg.proactive_mode == "smart"


def test_telegram_overrides_and_allowed_ids_filtering(isolated_config, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok-123")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "111, 222, notanid, 333")
    cfg = load_model_config()
    assert cfg.telegram_bot_token == "tok-123"
    assert cfg.telegram_allowed_user_ids == [111, 222, 333]  # non-int dropped


def test_line_port_clamped_and_invalid_ignored(isolated_config, monkeypatch):
    monkeypatch.setenv("LINE_BOT_PORT", "999999")  # clamp to 65535
    assert load_model_config().line_bot_port == 65535
    monkeypatch.setenv("LINE_BOT_PORT", "abc")  # ValueError -> default
    assert load_model_config().line_bot_port != 65535


def test_edge_retrieval_limit_clamped(isolated_config, monkeypatch):
    monkeypatch.setenv("KUMI_EDGE_TOOLS_RETRIEVAL_LIMIT", "500")  # clamp to 200
    assert load_model_config().edge_tools_retrieval_limit == 200
