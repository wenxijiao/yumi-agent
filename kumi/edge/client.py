"""Kumi Edge workspace initializer.

The WebSocket client logic has moved to :class:`kumi.sdk.KumiAgent`.
This module only provides ``init_workspace()`` which scaffolds the
``kumi_tools/`` directory and ``.env`` file for a new edge project.
"""

import os
import shutil
from importlib import resources as _pkg_resources

_STANDALONE_FILES = {
    "env.template": os.path.join("kumi_tools", ".env"),
    "gitignore.template": ".gitignore",
}

_AGENT_GUIDE_DEST = "AGENTS.md"
_TEMPLATE_SUBDIR = "kumi_tools"

_SUPPORTED_LANGS = (
    "python",
    "swift",
    "typescript",
    "cpp",
    "ue5",
    "go",
    "java",
    "csharp",
    "rust",
    "kotlin",
    "dart",
)

_LANG_SUBDIRS = {
    "python": "python",
    "swift": "swift",
    "typescript": "typescript",
    "cpp": "cpp",
    "ue5": "ue5",
    "go": "go",
    "java": "java",
    "csharp": "csharp",
    "rust": "rust",
    "kotlin": "kotlin",
    "dart": "dart",
}

# SDK source specs per language, resolved at runtime via __file__.
# "mode" controls copy strategy:
#   "files"  — copy listed files from sdk_rel into dest_subdir
#   "tree"   — copytree the entire sdk_rel directory into dest_subdir
_SDK_SOURCES = {
    "python": {
        "mode": "files",
        "sdk_rel": os.path.join("sdk", "python"),
        "files": ["agent_client.py"],
        "dest_subdir": os.path.join("python", "kumi_sdk"),
    },
    "swift": {
        "mode": "tree",
        "sdk_rel": os.path.join("sdk", "swift"),
        "ignore": [".build", ".swiftpm"],
        "dest_subdir": os.path.join("swift", "KumiSDK"),
    },
    "typescript": {
        "mode": "tree",
        "sdk_rel": os.path.join("sdk", "typescript"),
        "ignore": ["node_modules", "dist"],
        "dest_subdir": os.path.join("typescript", "kumi_sdk"),
    },
    "cpp": {
        "mode": "tree",
        "sdk_rel": os.path.join("sdk", "cpp"),
        "ignore": ["build", ".cache"],
        "dest_subdir": os.path.join("cpp", "KumiSDK"),
    },
    "ue5": {
        "mode": "tree",
        "sdk_rel": os.path.join("sdk", "ue5", "KumiSDK"),
        "ignore": ["Intermediate", "Binaries"],
        "dest_subdir": os.path.join("ue5", "KumiSDK"),
    },
    "go": {
        "mode": "tree",
        "sdk_rel": os.path.join("sdk", "go"),
        "ignore": ["vendor"],
        "dest_subdir": os.path.join("go", "kumi_sdk"),
    },
    "java": {
        "mode": "tree",
        "sdk_rel": os.path.join("sdk", "java"),
        "ignore": ["target", ".idea"],
        "dest_subdir": os.path.join("java", "kumi_sdk"),
    },
    "csharp": {
        "mode": "tree",
        "sdk_rel": os.path.join("sdk", "csharp"),
        "ignore": ["bin", "obj"],
        "dest_subdir": os.path.join("csharp", "kumi_sdk"),
    },
    "rust": {
        "mode": "tree",
        "sdk_rel": os.path.join("sdk", "rust"),
        "ignore": ["target", ".cargo"],
        "dest_subdir": os.path.join("rust", "kumi_sdk"),
    },
    "kotlin": {
        "mode": "tree",
        "sdk_rel": os.path.join("sdk", "kotlin", "src", "main", "kotlin", "io", "kumi", "sdk"),
        "ignore": [],
        "dest_subdir": os.path.join("kotlin", "src", "main", "kotlin", "io", "kumi", "sdk"),
    },
    "dart": {
        "mode": "tree",
        "sdk_rel": os.path.join("sdk", "dart"),
        "ignore": [".dart_tool", "build"],
        "dest_subdir": os.path.join("dart", "kumi_sdk"),
    },
}


def _find_sdk_root() -> str:
    """Locate the ``kumi/`` package root (parent of ``sdk/``)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _copy_agent_guide(workspace: str, created: list[str]) -> None:
    """Copy the canonical SDK guide to the generated edge project root."""
    dest_path = os.path.join(workspace, _AGENT_GUIDE_DEST)
    if os.path.exists(dest_path):
        return

    os.makedirs(workspace, exist_ok=True)

    src_path = os.path.join(_find_sdk_root(), "sdk", "AGENTS.md")
    if os.path.isfile(src_path):
        shutil.copy2(src_path, dest_path)
        created.append(_AGENT_GUIDE_DEST)
        return

    try:
        guide = _pkg_resources.files("kumi.sdk") / "AGENTS.md"
        if not guide.is_file():
            return
        data = guide.read_bytes()
    except Exception:
        return

    with open(dest_path, "wb") as fh:
        fh.write(data)
    created.append(_AGENT_GUIDE_DEST)


def init_workspace(
    target_dir: str | None = None,
    lang: str | list[str] | None = None,
) -> list[str]:
    """Ensure a Kumi Edge workspace is complete in *target_dir*.

    Args:
        target_dir: Workspace root (defaults to cwd).
        lang: Single language, a list of languages, or ``None`` for all
              supported languages. Only template + SDK files for the
              selected language(s) are created.

    Existing files are never overwritten, so this is safe to run
    repeatedly.  Returns a list of relative paths that were created.
    """
    workspace = target_dir or os.getcwd()

    template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "template")
    if not os.path.isdir(template_dir):
        try:
            ref = _pkg_resources.files("kumi.edge") / "template"
            template_dir = str(ref)
        except Exception:
            pass
    if not os.path.isdir(template_dir):
        raise FileNotFoundError(f"Template directory not found: {template_dir}")

    # Determine which languages to scaffold
    if lang is None:
        langs = list(_SUPPORTED_LANGS)
    elif isinstance(lang, str):
        one = lang.lower().strip()
        if one not in _SUPPORTED_LANGS:
            raise ValueError(f"Unsupported language: {one!r}. Supported: {', '.join(_SUPPORTED_LANGS)}")
        langs = [one]
    else:
        langs = []
        for item in lang:
            for part in str(item).split(","):
                lang_code = part.strip().lower()
                if not lang_code:
                    continue
                if lang_code not in _SUPPORTED_LANGS:
                    raise ValueError(f"Unsupported language: {lang_code!r}. Supported: {', '.join(_SUPPORTED_LANGS)}")
                langs.append(lang_code)
        seen: set[str] = set()
        langs = [x for x in langs if not (x in seen or seen.add(x))]
        if not langs:
            langs = list(_SUPPORTED_LANGS)

    created: list[str] = []
    _copy_agent_guide(workspace, created)

    # 1) Copy template tree (filtered by language)
    template_subdir = os.path.join(template_dir, _TEMPLATE_SUBDIR)
    if os.path.isdir(template_subdir):
        skip_dirs = {v for k, v in _LANG_SUBDIRS.items() if k not in langs}

        for dirpath, dirnames, filenames in os.walk(template_subdir):
            rel_dir = os.path.relpath(dirpath, template_dir)

            # Skip language directories not in the selected set
            parts = rel_dir.replace("\\", "/").split("/")
            if len(parts) >= 2 and parts[1] in skip_dirs:
                dirnames.clear()
                continue

            dest_dir = os.path.join(workspace, rel_dir)
            if not os.path.isdir(dest_dir):
                os.makedirs(dest_dir, exist_ok=True)
                created.append(f"{rel_dir}/")

            for fname in filenames:
                src_file = os.path.join(dirpath, fname)
                dest_file = os.path.join(dest_dir, fname)
                if not os.path.exists(dest_file):
                    shutil.copy2(src_file, dest_file)
                    created.append(os.path.relpath(dest_file, workspace))

    # 2) Copy SDK source files for each selected language
    sdk_root = _find_sdk_root()

    for lang_key in langs:
        spec = _SDK_SOURCES.get(lang_key)
        if not spec:
            continue

        src_dir = os.path.join(sdk_root, spec["sdk_rel"])
        dest_dir = os.path.join(workspace, _TEMPLATE_SUBDIR, spec["dest_subdir"])

        if not os.path.isdir(src_dir):
            continue

        mode = spec.get("mode", "files")

        if mode == "tree":
            ignore_dirs = set(spec.get("ignore", []))
            shutil.copytree(
                src_dir,
                dest_dir,
                ignore=shutil.ignore_patterns(*ignore_dirs) if ignore_dirs else None,
                dirs_exist_ok=True,
            )
            for dirpath, _, filenames in os.walk(dest_dir):
                rel = os.path.relpath(dirpath, workspace)
                created.append(f"{rel}/")
                for fname in filenames:
                    created.append(os.path.join(rel, fname))
        else:
            if not os.path.isdir(dest_dir):
                os.makedirs(dest_dir, exist_ok=True)
                created.append(os.path.relpath(dest_dir, workspace) + "/")
            for fname in spec.get("files", []):
                src_file = os.path.join(src_dir, fname)
                dest_file = os.path.join(dest_dir, fname)
                if not os.path.exists(dest_file) and os.path.isfile(src_file):
                    shutil.copy2(src_file, dest_file)
                    created.append(os.path.relpath(dest_file, workspace))

    # 3) Standalone files (.env, .gitignore)
    for src_name, dest_name in _STANDALONE_FILES.items():
        src_path = os.path.join(template_dir, src_name)
        dest_path = os.path.join(workspace, dest_name)

        if os.path.exists(dest_path):
            continue
        if not os.path.isfile(src_path):
            continue

        dest_parent = os.path.dirname(dest_path)
        if dest_parent and not os.path.isdir(dest_parent):
            os.makedirs(dest_parent, exist_ok=True)

        shutil.copy2(src_path, dest_path)
        created.append(dest_name)

    return created
