"""Cleanup helpers for config and memory storage."""

import kumi.core.features.config as config
import kumi.core.features.config.paths as config_paths


def test_cleanup_memory_data_preserves_config_and_removes_memory(tmp_path, monkeypatch):
    config_dir = tmp_path / ".kumi"
    memory_dir = config_dir / "memory"
    legacy_dir = tmp_path / "legacy-memory"

    monkeypatch.setattr(config_paths, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config_paths, "CONFIG_PATH", config_dir / "config.json")
    monkeypatch.setattr(config_paths, "MEMORY_DIR", memory_dir)
    monkeypatch.setattr(config_paths, "LEGACY_MEMORY_DIR", legacy_dir)

    config_dir.mkdir(parents=True)
    memory_dir.mkdir()
    legacy_dir.mkdir()
    (config_dir / "config.json").write_text('{"chat_model":"demo"}', encoding="utf-8")
    (memory_dir / "data.txt").write_text("memory", encoding="utf-8")
    (legacy_dir / "legacy.txt").write_text("legacy", encoding="utf-8")

    removed = config.cleanup_memory_data()

    assert config_dir.exists()
    assert (config_dir / "config.json").exists()
    assert not memory_dir.exists()
    assert not legacy_dir.exists()
    assert set(removed) == {memory_dir, legacy_dir}


def test_cleanup_user_data_removes_config_dir_and_legacy_memory(tmp_path, monkeypatch):
    config_dir = tmp_path / ".kumi"
    memory_dir = config_dir / "memory"
    legacy_dir = tmp_path / "legacy-memory"

    monkeypatch.setattr(config_paths, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(config_paths, "CONFIG_PATH", config_dir / "config.json")
    monkeypatch.setattr(config_paths, "MEMORY_DIR", memory_dir)
    monkeypatch.setattr(config_paths, "LEGACY_MEMORY_DIR", legacy_dir)

    memory_dir.mkdir(parents=True)
    legacy_dir.mkdir()
    (config_dir / "config.json").write_text('{"chat_model":"demo"}', encoding="utf-8")

    removed = config.cleanup_user_data()

    assert not config_dir.exists()
    assert not legacy_dir.exists()
    assert config_dir in removed
    assert legacy_dir in removed
    assert memory_dir not in removed
