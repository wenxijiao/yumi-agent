"""Fail when Yumi package and SDK version declarations drift apart."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _match(path: str, pattern: str) -> str:
    text = (ROOT / path).read_text(encoding="utf-8")
    match = re.search(pattern, text, re.MULTILINE)
    if match is None:
        raise SystemExit(f"Could not read a version from {path}")
    return match.group(1)


def _json_version(path: str) -> str:
    data = json.loads((ROOT / path).read_text(encoding="utf-8"))
    version = data.get("version")
    if not isinstance(version, str):
        raise SystemExit(f"Could not read a version from {path}")
    return version


def declared_versions() -> dict[str, str]:
    return {
        "Python package": _match("pyproject.toml", r'^version = "([^"]+)"'),
        "Python fallback": _match("yumi/__init__.py", r'^\s*__version__ = "([^"]+)"'),
        "TypeScript SDK": _json_version("yumi/sdk/typescript/package.json"),
        "TypeScript lockfile": _json_version("yumi/sdk/typescript/package-lock.json"),
        "Dart SDK": _match("yumi/sdk/dart/pubspec.yaml", r"^version:\s*([^\s]+)"),
        "Kotlin SDK": _match("yumi/sdk/kotlin/build.gradle.kts", r'^version = "([^"]+)"'),
        "Rust SDK": _match("yumi/sdk/rust/Cargo.toml", r'^version = "([^"]+)"'),
        "Java SDK": _match("yumi/sdk/java/pom.xml", r"<version>([^<]+)</version>"),
        "C# SDK": _match("yumi/sdk/csharp/YumiSDK.csproj", r"<Version>([^<]+)</Version>"),
        "Web UI": _json_version("yumi/ui/frontend/package.json"),
        "Web UI lockfile": _json_version("yumi/ui/frontend/package-lock.json"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", help="Release tag to compare, such as v0.0.2")
    args = parser.parse_args()

    versions = declared_versions()
    expected = versions["Python package"]
    mismatches = {name: version for name, version in versions.items() if version != expected}

    if args.tag:
        tag_version = args.tag.removeprefix("v")
        if tag_version != expected:
            mismatches[f"Git tag {args.tag}"] = tag_version

    if mismatches:
        details = "\n".join(f"  - {name}: {version} (expected {expected})" for name, version in mismatches.items())
        raise SystemExit(f"Version declarations are not synchronized:\n{details}")

    print(f"All package versions are synchronized at {expected}.")


if __name__ == "__main__":
    main()
