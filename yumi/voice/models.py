"""Pinned first-run wake model download with safe, atomic cache installation."""

from __future__ import annotations

import hashlib
import shutil
import tarfile
import tempfile
from pathlib import Path

import requests

MODEL = "sherpa-onnx-kws-zipformer-gigaspeech-3.3M-2024-01-01"
URL = f"https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/{MODEL}.tar.bz2"
SHA256 = "f170013b4716e41b62b9bfd809687c207cef798ef9bc6534d524e17af9b6561a"
FILES = [f"{part}-epoch-12-avg-2-chunk-16-left-64.onnx" for part in ("encoder", "decoder", "joiner")] + [
    "tokens.txt",
    "bpe.model",
]


def install_archive(archive: Path, destination: Path) -> None:
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise RuntimeError("Wake model checksum mismatch; download aborted. Try again.")
    with tarfile.open(archive, "r:bz2") as tar:
        for name in FILES:
            member = tar.getmember(f"{MODEL}/{name}")
            if not member.isfile() or member.size > 64 * 1024 * 1024:
                raise RuntimeError("Invalid wake model archive")
            source = tar.extractfile(member)
            if source is None:
                raise RuntimeError("Missing wake model archive entry")
            with source, (destination / name).open("wb") as target:
                shutil.copyfileobj(source, target)


def ensure_model(cache: Path | None = None) -> str:
    cache = cache or Path.home() / ".yumi" / "models" / "wake"
    target = cache / MODEL
    if all((target / name).is_file() for name in FILES):
        return str(target)
    cache.mkdir(parents=True, exist_ok=True)
    print("Preparing Hey Yumi wake model (17 MB, downloaded once from sherpa-onnx)…")
    with tempfile.TemporaryDirectory(prefix=".download-", dir=cache) as temp:
        temp = Path(temp)
        archive = temp / "model.tar.bz2"
        with requests.get(URL, stream=True, timeout=(15, 60)) as response:
            response.raise_for_status()
            total = 0
            with archive.open("wb") as output:
                for chunk in response.iter_content(256 * 1024):
                    total += len(chunk)
                    if total > 32 * 1024 * 1024:
                        raise RuntimeError("Wake model download exceeds expected size")
                    output.write(chunk)
        prepared = temp / "ready"
        prepared.mkdir()
        install_archive(archive, prepared)
        if target.exists():
            if all((target / name).is_file() for name in FILES):
                return str(target)
            raise RuntimeError(f"Incomplete model at {target}; remove it and restart --voice.")
        try:
            prepared.rename(target)
        except OSError:
            if not all((target / name).is_file() for name in FILES):
                raise
    return str(target)
