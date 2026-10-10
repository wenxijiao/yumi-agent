"""Own a local server only when --voice starts it; reuse existing servers."""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import time
from pathlib import Path

import requests


@contextlib.contextmanager
def local_server(connection, *, auto_start: bool):
    try:
        connection.request("GET", "/assistant", timeout=3)
    except requests.ConnectionError:
        if not auto_start:
            raise RuntimeError(f"Cannot reach {connection.base_url}. Check --voice-server.") from None
    else:
        yield
        return
    from yumi.cli.runners import _preflight_models
    from yumi.core.features.config import save_model_config
    from yumi.core.features.tts.system_provider import resolve_system_command

    config = _preflight_models()
    if config.stt_provider in ("", "disabled"):
        config.stt_provider, config.stt_model = "whisper", "base"
        print("Local voice input: Whisper base (downloads weights on first use).")
    if config.tts_provider in ("", "disabled"):
        if not resolve_system_command():
            raise RuntimeError(
                "Local speech output needs espeak-ng on Linux, or a TTS provider configured with yumi --setup."
            )
        config.tts_provider = "system"
        print("Local spoken replies: system voice.")
    save_model_config(config)
    log_path = Path.home() / ".yumi" / "voice-server.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "YUMI_HOST": "127.0.0.1", "YUMI_PORT": "8000", "YUMI_VOICE_ENABLED": "0"}
    with log_path.open("a") as log:
        process = subprocess.Popen(
            [sys.executable, "-m", "yumi.core.api"], stdout=log, stderr=log, stdin=subprocess.DEVNULL, env=env
        )
        try:
            print(f"Starting local Yumi… logs: {log_path}")
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"Local server stopped. See {log_path}")
                try:
                    connection.request("GET", "/assistant", timeout=2)
                    break
                except requests.ConnectionError:
                    time.sleep(0.3)
            else:
                raise RuntimeError(f"Local server startup timed out. See {log_path}")
            yield
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
