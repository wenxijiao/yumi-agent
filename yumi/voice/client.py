"""Microphone-side voice client for either a local Yumi server or Yumi Nexus."""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import requests

from yumi.voice.sherpa_wake import SherpaHeyYumiWake

NEXUS_URL = "https://api.yumi.nexus"
LOCAL_URL = "http://127.0.0.1:8000"
CLIENT_FILE = Path.home() / ".yumi" / "voice-client.json"


@dataclass
class VoiceConnection:
    base_url: str
    token: str = ""

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def request(self, method: str, path: str, **kwargs):
        response = requests.request(
            method, self.base_url + path, headers=self.headers(), timeout=kwargs.pop("timeout", 60), **kwargs
        )
        response.raise_for_status()
        return response


def _saved_connection() -> dict:
    if not CLIENT_FILE.exists():
        return {}
    if CLIENT_FILE.is_symlink():
        raise RuntimeError("Voice client credential file must not be a symlink")
    return json.loads(CLIENT_FILE.read_text())


def _save_connection(server: str, name: str, token: str) -> None:
    CLIENT_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if CLIENT_FILE.is_symlink():
        raise RuntimeError("Voice client credential file must not be a symlink")
    import tempfile

    fd, temp = tempfile.mkstemp(prefix=".voice-client-", dir=CLIENT_FILE.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump({"server": server, "device_name": name, "access_token": token}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, 0o600)
        os.replace(temp, CLIENT_FILE)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def _login_request(server: str, action: str, body: dict) -> dict:
    response = requests.post(server + "/nexus/edge-login/" + action, json=body, timeout=20, allow_redirects=False)
    if response.status_code == 429 and action == "token":
        return {"status": "slow_down"}
    response.raise_for_status()
    return response.json()


def login_nexus(server: str, name: str, *, open_browser: bool = True) -> VoiceConnection:
    parsed = urlsplit(server)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}):
        raise RuntimeError("Nexus sign-in requires HTTPS (HTTP is allowed only for localhost)")
    started = _login_request(server, "start", {"edge_name": name, "client_kind": "voice"})
    print(f"Connect voice device {name}: {started['verification_uri_complete']}")
    print(f"Confirm the code {started['user_code']} in your browser.")
    if open_browser:
        webbrowser.open(started["verification_uri_complete"])
    deadline = time.monotonic() + min(int(started.get("expires_in", 600)), 600)
    interval = max(1, int(started.get("interval", 5)))
    saved = False
    try:
        while time.monotonic() < deadline:
            time.sleep(interval)
            result = _login_request(server, "token", {"device_code": started["device_code"]})
            if result.get("status") in {"authorization_pending", "slow_down"}:
                interval = min(30, interval + (5 if result.get("status") == "slow_down" else 0))
                continue
            token = result.get("access_token")
            if result.get("status") != "approved" or not isinstance(token, str):
                raise RuntimeError("Voice device sign-in failed")
            _save_connection(server, name, token)
            saved = True
            try:
                _login_request(server, "ack", {"device_code": started["device_code"]})
            except requests.RequestException:
                pass
            print(f"Signed in as {result.get('account') or 'your Yumi account'}.")
            return VoiceConnection(server, token)
        raise RuntimeError("Voice device sign-in timed out")
    finally:
        if not saved:
            try:
                _login_request(server, "cancel", {"device_code": started["device_code"]})
            except requests.RequestException:
                pass


def connect(mode: str, server: str | None, name: str, *, open_browser: bool = True) -> VoiceConnection:
    if mode == "local":
        return VoiceConnection((server or LOCAL_URL).rstrip("/"))
    base = (server or NEXUS_URL).rstrip("/")
    stored = _saved_connection()
    if stored.get("server") == base and stored.get("device_name") == name and stored.get("access_token"):
        connection = VoiceConnection(base, stored["access_token"])
        try:
            connection.request("GET", "/assistant", timeout=20)
            return connection
        except requests.HTTPError as exc:
            if exc.response is None or exc.response.status_code != 401:
                raise
            CLIENT_FILE.unlink(missing_ok=True)
            print("Saved voice sign-in expired; sign in again.")
    connection = login_nexus(base, name, open_browser=open_browser)
    connection.request("GET", "/assistant", timeout=20)
    return connection


def logout_nexus() -> None:
    stored = _saved_connection()
    if stored.get("server") and stored.get("access_token"):
        connection = VoiceConnection(stored["server"], stored["access_token"])
        try:
            rows = connection.request("GET", "/tenancy/connections", timeout=20).json()["connections"]
            current = next((row for row in rows if row.get("kind") == "voice" and row.get("current")), None)
            if current:
                connection.request("DELETE", f"/tenancy/connections/{current['id']}", timeout=20)
        except requests.RequestException as exc:
            if not isinstance(exc, requests.HTTPError) or exc.response is None or exc.response.status_code != 401:
                raise RuntimeError("Could not revoke the voice credential on Nexus; try again while online") from exc
    CLIENT_FILE.unlink(missing_ok=True)


async def run_client(
    connection,
    wake,
    device,
    output_device=None,
    followup_seconds=20,
    cue_volume=70,
    audio_mode="full-duplex",
    silence_ms=2500,
):
    from yumi.voice.conversation import VoiceSession
    from yumi.voice.duplex import DuplexAudio
    from yumi.voice.media_wait import wait_for_media

    resume = False
    while True:
        if audio_mode == "half-duplex":
            from yumi.voice.half_duplex import HalfDuplexAudio

            audio = HalfDuplexAudio(device, output_device)
        else:
            audio = DuplexAudio(device, output_device)
        audio.cue_volume = cue_volume
        session = VoiceSession(connection, audio, wake, followup_seconds=followup_seconds, silence_ms=silence_ms)
        session.start_awake = resume
        try:
            result = await session.run()
            if result != "paused" or not session.media_watch:
                return result
            # Close first, including fallback paths; polling never opens input.
            audio.close()
            if not await wait_for_media(session.http, session.media_watch):
                return "paused"
            resume = True
            wake.reset()
        finally:
            await session.close()


def choose_mode() -> str:
    """Choose the voice backend once, before opening the microphone."""
    if not sys.stdin.isatty():
        raise SystemExit("Choose --voice-mode local or --voice-mode nexus when running without a terminal.")
    print("Hey Yumi — choose how to connect:")
    print("  1) Local model (Yumi server on this computer)")
    print("  2) Sign in to Yumi Nexus")
    while True:
        try:
            answer = input("Choose 1 or 2: ").strip().lower()
        except EOFError as exc:
            raise SystemExit("No voice mode selected.") from exc
        if answer in {"1", "local"}:
            return "local"
        if answer in {"2", "nexus"}:
            return "nexus"
        print("Please choose 1 or 2.")


def main(
    *,
    mode: str | None,
    server: str | None,
    name: str | None,
    model_dir: str | None,
    keywords_file: str | None,
    device: int | None,
    open_browser: bool,
    logout: bool,
    output_device: int | None = None,
    list_devices: bool = False,
    followup_seconds: int = 20,
    wake_sensitivity: str = "balanced",
    cue_volume: int = 70,
    audio_mode: str | None = None,
    silence_ms: int = 2500,
) -> int:
    import contextlib

    if logout:
        logout_nexus()
        print("Voice device credentials removed from this computer.")
        return 0
    if list_devices:
        import sounddevice

        print(sounddevice.query_devices())
        return 0
    mode = mode or choose_mode()
    from yumi.core.features.config import load_model_config
    from yumi.voice.duplex import device_settings, select_input_device
    from yumi.voice.local_server import local_server
    from yumi.voice.models import ensure_model

    config = load_model_config()
    audio_mode = audio_mode or config.voice_audio_mode
    device = device if device is not None else config.voice_input_device
    try:
        device = select_input_device(device, output_device)
        device_settings(device, output_device)
    except Exception as exc:
        raise SystemExit(
            f"Audio device unavailable: {exc}. Check microphone permissions and --voice --voice-list-devices."
        ) from exc
    model_dir = model_dir or os.getenv("YUMI_VOICE_MODEL_DIR") or config.voice_sherpa_model_dir or ensure_model()
    keywords_file = keywords_file or config.voice_sherpa_keywords_file
    name = name or socket.gethostname() or "Yumi voice"
    wake = SherpaHeyYumiWake(model_dir, keywords_file, sensitivity=wake_sensitivity)
    try:
        connection = connect(mode, server, name, open_browser=open_browser)
        backend = local_server(connection, auto_start=not server) if mode == "local" else contextlib.nullcontext()
        with backend:
            while (
                asyncio.run(
                    run_client(
                        connection, wake, device, output_device, followup_seconds, cue_volume, audio_mode, silence_ms
                    )
                )
                == "paused"
            ):
                if not sys.stdin.isatty():
                    break
                input("Microphone released. Press Enter to resume Hey Yumi, or Ctrl+C to quit: ")
                wake.reset()
    except KeyboardInterrupt:
        print("\nVoice client stopped.")
    except Exception as exc:
        print(f"Cannot run voice: {exc}", file=sys.stderr)
        return 1
    finally:
        wake.close()
    return 0
