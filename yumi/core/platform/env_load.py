"""Load optional dotenv files so ``YUMI_*``, ``HF_*``, etc. apply without manual export."""

from __future__ import annotations

from pathlib import Path


def load_yumi_dotenv() -> None:
    """Load ``~/.yumi/.env`` then ``./.env``; never override existing OS environment."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    config_dir = Path.home() / ".yumi"
    config_dir.mkdir(parents=True, exist_ok=True)
    load_dotenv(config_dir / ".env", override=False)
    load_dotenv(Path.cwd() / ".env", override=False)
