"""Install optional ('extra') feature dependencies on demand.

The base ``pip install yumi-agent`` is intentionally batteries-included for
chat providers, messaging bridges, STT, microphone voice mode, cloud TTS/STT,
local FastEmbed embeddings, and file ingestion. The web UI now ships pre-built
and is served by the core server (no extra install). Only local-GPU Qwen TTS
stays out of the base install.

This module lets the setup wizard and the CLI offer that extra the moment a user
turns the feature on, instead of failing later with a missing-package error.
"""

from __future__ import annotations

import importlib
import importlib.util
import subprocess
import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import requires as _dist_requires

_DIST = "yumi-agent"

# feature -> (extra name, module to probe for "already installed?", label)
_FEATURES: dict[str, tuple[str, str, str]] = {
    "tts-local": ("tts-local", "qwen_tts", "Qwen3-TTS running locally (GPU)"),
}


def is_feature_installed(feature: str) -> bool:
    """True if *feature*'s probe module can be imported."""
    _, module, _ = _FEATURES[feature]
    return importlib.util.find_spec(module) is not None


def _extra_requirements(extra: str) -> list[str]:
    """Requirement strings declared under ``extra == "<extra>"`` in our metadata.

    Reading the installed distribution's own metadata works whether yumi-agent
    was installed from PyPI, from git, or editable from source — so we never
    depend on ``yumi-agent[extra]`` resolving against an index that may not have
    published us yet.
    """
    try:
        reqs = _dist_requires(_DIST) or []
    except PackageNotFoundError:
        return []
    out: list[str] = []
    for r in reqs:
        if f'extra == "{extra}"' in r or f"extra == '{extra}'" in r:
            out.append(r.split(";", 1)[0].strip())
    return out


def ensure_feature_installed(feature: str, *, assume_yes: bool = False) -> bool:
    """Ensure *feature*'s optional deps are importable, offering to install them.

    Returns ``True`` if the feature is ready (already present or installed just
    now), ``False`` if the user declined or the install did not make the package
    importable (e.g. a missing system library).
    """
    extra, module, label = _FEATURES[feature]
    if is_feature_installed(feature):
        return True

    print()
    if assume_yes:
        answer = "y"
    else:
        print(f"  {label} needs an optional package that isn't installed yet.")
        answer = input("  Install it now? (Y/n): ").strip().lower()
    if answer in ("n", "no"):
        print(f"  Skipped. Install later with:  pip install 'yumi-agent[{extra}]'")
        return False

    targets = _extra_requirements(extra) or [f"{_DIST}[{extra}]"]
    print(f"  Installing: {' '.join(targets)}")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", *targets], check=True)
    except (subprocess.CalledProcessError, OSError) as exc:
        print(f"  Install failed ({exc}).")
        print(f"  Try manually:  pip install 'yumi-agent[{extra}]'")
        return False

    importlib.invalidate_caches()
    if not is_feature_installed(feature):
        print(f"  Installed, but '{module}' still can't be imported.")
        return False
    print(f"  {label} is ready.")
    return True
