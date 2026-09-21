"""Guard L1 from concrete L2/L3 branding and app-specific content."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_ROOTS = (
    ROOT / "README.md",
    ROOT / "CHANGELOG.md",
    ROOT / "llms.txt",
    ROOT / "docker-compose.yml",
    ROOT / "docs",
    ROOT / "yumi",
    ROOT / "tests",
)

CONCRETE_FORBIDDEN_RE = re.compile(
    "|".join(
        [
            r"\byumi-enterprise\b",
            r"\byumi-nexus\b",
            r"\byumi_nexus\b",
            r"\byumi nexus(?: ltd| limited)?\b",
            r"/nexus/",
            r"\bmi" r"rai\b",
            r"\bku" r"mi\b",
            r"\bmemori\b",
            r"\btemi\b",
            r"\bcreate_temi\b",
            r"\bmugi\b",
            r"\bcreate_seed\b",
            r"\bcheck_in_seed\b",
        ]
    ),
    re.IGNORECASE,
)

HIGHER_LAYER_FORBIDDEN_RE = re.compile(
    "|".join(
        [
            r"\brelay\b",
            r"\bmulti-tenant\b",
            r"\btenant\b",
            r"\btenancy\b",
        ]
    ),
    re.IGNORECASE,
)

EXCLUDED_DIR_PARTS = {"__pycache__", ".pytest_cache", ".web", "node_modules"}
# Files that legitimately describe the L1<->L2/L3 boundary itself (how to upgrade
# to the enterprise build, or stripping enterprise env vars for test isolation).
# They reference enterprise terms to *describe* the boundary, not to leak L2/L3
# implementation into L1, so they are exempt from the term scan.
EXCLUDED_FILES = {
    Path(__file__).name,
    "UPGRADING_TO_ENTERPRISE.md",
    "conftest.py",
}


# The public CLI now explicitly connects to hosted Yumi as well as OSS servers.
# Allow only its public product label and the device-login client endpoint in
# these integration surfaces. Backend packages, private app content and server
# implementation terms remain forbidden everywhere outside the existing guide.
PUBLIC_EDGE_LABEL_FILES = {
    "README.md",
    "CHANGELOG.md",
    "docs/EDGE_TOOLS.md",
    "docs/HTTP_API.md",
    "yumi/cli/commands.py",
    "yumi/edge/connection.py",
    "yumi/edge/template/env.template",
    "yumi/edge/template/yumi_tools/README.md",
}


def _public_edge_client_reference(path: Path, text: str, match: re.Match[str]) -> bool:
    relative = path.relative_to(ROOT).as_posix()
    if relative in PUBLIC_EDGE_LABEL_FILES and match.group(0).casefold() == "yumi nexus":
        return True
    return (
        relative == "yumi/edge/login.py"
        and match.group(0) == "/nexus/"
        and text[match.end() :].startswith("edge-login/")
    )


def _text_files():
    for root in SCAN_ROOTS:
        if root.is_file():
            yield root
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.name in EXCLUDED_FILES:
                continue
            if any(part in EXCLUDED_DIR_PARTS for part in path.relative_to(ROOT).parts):
                continue
            if path.suffix.lower() in {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf"}:
                continue
            yield path


def test_l1_has_no_concrete_l2_l3_brand_or_app_terms():
    offenders: list[str] = []
    for path in _text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel_parts = path.relative_to(ROOT).parts
        patterns = [CONCRETE_FORBIDDEN_RE]
        if "sdk" not in rel_parts:
            patterns.append(HIGHER_LAYER_FORBIDDEN_RE)
        for pattern in patterns:
            for match in pattern.finditer(text):
                if _public_edge_client_reference(path, text, match):
                    continue
                rel = path.relative_to(ROOT)
                offenders.append(f"{rel}:{text.count(chr(10), 0, match.start()) + 1}: {match.group(0)!r}")

    assert not offenders, "L1 should stay free of concrete L2/L3 or app-specific terms:\n" + "\n".join(offenders)
