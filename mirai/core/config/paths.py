"""Filesystem paths for Mirai config and LanceDB memory storage."""

import shutil
from pathlib import Path

CONFIG_DIR = Path.home() / ".mirai"
CONFIG_PATH = CONFIG_DIR / "config.json"
MEMORY_DIR = CONFIG_DIR / "memory"
# Legacy bundled DB shipped under mirai/core/memories/.lancedb (mirai/core is parent of this config/ dir).
LEGACY_MEMORY_DIR = Path(__file__).resolve().parent.parent / "memories" / ".lancedb"


def ensure_config_dir() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # Restrict to owner-only since config.json holds API keys and tokens.
    try:
        CONFIG_DIR.chmod(0o700)
    except OSError:
        pass


def ensure_memory_dir() -> None:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)


def get_memory_dir() -> Path:
    ensure_memory_dir()
    return MEMORY_DIR


def get_legacy_memory_dir() -> Path:
    return LEGACY_MEMORY_DIR


def migrate_legacy_memory_dir() -> Path:
    target = get_memory_dir()
    legacy = get_legacy_memory_dir()

    if target.exists() and any(target.iterdir()):
        return target

    if not legacy.exists():
        return target

    if target.exists():
        target.rmdir()
    shutil.move(str(legacy), str(target))
    return target


def cleanup_memory_data() -> list[Path]:
    removed_paths: list[Path] = []

    if MEMORY_DIR.exists():
        shutil.rmtree(MEMORY_DIR)
        removed_paths.append(MEMORY_DIR)

    legacy = get_legacy_memory_dir()
    if legacy.exists():
        shutil.rmtree(legacy)
        removed_paths.append(legacy)

    return removed_paths


def cleanup_user_data() -> list[Path]:
    removed_paths: list[Path] = []

    if CONFIG_DIR.exists():
        shutil.rmtree(CONFIG_DIR)
        removed_paths.append(CONFIG_DIR)

    removed_paths.extend(cleanup_memory_data())
    return removed_paths
