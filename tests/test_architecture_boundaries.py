"""Guard the platform / features / api dependency rule.

These tests parse import statements (AST) so they catch *import-time* edges
only — function-local (lazy) imports and ``if TYPE_CHECKING:`` imports are
intentionally allowed, matching the rule documented in docs/ARCHITECTURE.md:

* features depend on platform, never the reverse;
* features never import each other;
* platform has no import-time dependency on features or api;
* only api (the composition root) may import both platform and features.
"""

from __future__ import annotations

import ast
import pathlib

CORE = pathlib.Path(__file__).resolve().parent.parent / "kumi" / "core"


def _runtime_imports(path: pathlib.Path) -> list[str]:
    """Module-level import targets, excluding `if TYPE_CHECKING:` blocks."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[str] = []

    def visit_body(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, ast.ImportFrom) and node.module:
                out.append(node.module)
            elif isinstance(node, ast.Import):
                out.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.If):
                # Skip `if TYPE_CHECKING:` guarded imports (never run at import time).
                test = node.test
                is_type_checking = (
                    isinstance(test, ast.Name) and test.id == "TYPE_CHECKING"
                ) or (isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING")
                if not is_type_checking:
                    visit_body(node.body)
                visit_body(node.orelse)
            # NOTE: function/class bodies are not descended into -> lazy imports allowed.

    visit_body(tree.body)
    return out


def _modules_under(pkg: str) -> list[pathlib.Path]:
    root = CORE / pkg
    return [p for p in root.rglob("*.py") if "__pycache__" not in str(p)]


def test_platform_has_no_import_time_dependency_on_features_or_api():
    offenders: list[str] = []
    for path in _modules_under("platform"):
        for mod in _runtime_imports(path):
            if mod.startswith("kumi.core.features") or mod.startswith("kumi.core.api"):
                offenders.append(f"{path.relative_to(CORE)} imports {mod}")
    assert not offenders, "platform must not import features/api at module load:\n" + "\n".join(offenders)


def test_features_do_not_import_api():
    offenders: list[str] = []
    for path in _modules_under("features"):
        for mod in _runtime_imports(path):
            if mod.startswith("kumi.core.api"):
                offenders.append(f"{path.relative_to(CORE)} imports {mod}")
    assert not offenders, "features must not import the api composition layer:\n" + "\n".join(offenders)


# Foundational features any other feature may depend on (config/prompts are
# used pervasively, like platform). Kept explicit so *new* cross-feature
# coupling still trips the test.
_FOUNDATIONAL_FEATURES = {"config", "prompts"}

# Known, accepted cross-feature edges that are not foundational. Candidates for
# future cleanup (e.g. share the bit via platform), but not regressions today.
_ALLOWED_FEATURE_EDGES = {
    ("prompts", "proactive"),  # prompt composition reuses proactive timezone utils
    ("stt", "uploads"),        # stt router reuses the uploads service
    ("tools", "edge"),         # tools router pushes confirmation policy to edge peers
}


def test_features_do_not_import_each_other():
    offenders: list[str] = []
    for path in _modules_under("features"):
        own_feature = path.relative_to(CORE / "features").parts[0]
        for mod in _runtime_imports(path):
            prefix = "kumi.core.features."
            if not mod.startswith(prefix):
                continue
            target_feature = mod[len(prefix) :].split(".")[0]
            if target_feature == own_feature or target_feature in _FOUNDATIONAL_FEATURES:
                continue
            if (own_feature, target_feature) in _ALLOWED_FEATURE_EDGES:
                continue
            offenders.append(f"{path.relative_to(CORE)} imports {mod}")
    assert not offenders, (
        "unexpected cross-feature import (share via platform, or add to the "
        "documented allowlist if intentional):\n" + "\n".join(offenders)
    )
