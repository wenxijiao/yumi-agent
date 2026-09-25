"""Microphone-side voice client for either a local Yumi server or Yumi Nexus."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import socket
import sys
import time
import uuid
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import requests

from yumi.voice.audio_source import SoundDeviceSource
from yumi.voice.runtime import pcm_to_wav_bytes
from yumi.voice.segmenter import UtteranceCollector, _VadBackend
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
    response = requests.post(
        server + "/nexus/edge-login/" + action, json=body, timeout=20, allow_redirects=False
    )
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


def voice_turn(connection: VoiceConnection, wav: bytes) -> str:
    snapshot = connection.request("GET", "/assistant").json()
    state = snapshot.get("conversation", snapshot)
    session_id = state["session_id"]
    revision = state.get("revision")
    recording = connection.request(
        "POST", "/assistant/voice",
        json={
            "request_id": str(uuid.uuid4()),
            "session_id": session_id,
            "content_base64": base64.b64encode(wav).decode("ascii"),
        },
        timeout=120,
    ).json()
    print(f"You: {recording['transcript']}")
    response = connection.request(
        "POST", "/chat",
        json={
            "prompt": recording["transcript"],
            "session_id": session_id,
            "personal": True,
            "voice_id": recording["id"],
            "reply_voice": True,
            "revision": revision,
            "channel": "app",
        },
        stream=True,
        timeout=(10, 300),
    )
    pieces: list[str] = []
    turn_id = ""
    try:
        for line in response.iter_lines():
            if not line:
                continue
            event = json.loads(line)
            kind = event.get("type")
            if kind == "turn_phase":
                turn_id = event.get("turn_id") or turn_id
            elif kind == "text":
                pieces.append(str(event.get("content") or ""))
            elif kind == "tool_confirmation":
                # Never grant a tool action just because a wake word was heard.
                connection.request(
                    "POST", "/tools/confirm",
                    json={"call_id": event["call_id"], "decision": "deny"},
                )
                print("Tool action needs confirmation in the Yumi app; denied for this voice turn.")
            elif kind == "error":
                raise RuntimeError(str(event.get("content") or "Yumi chat failed"))
    finally:
        response.close()
    reply = "".join(pieces).strip()
    print(f"Yumi: {reply}")
    if turn_id and reply:
        summary = connection.request(
            "POST", "/assistant/voice/reply", json={"turn_id": turn_id}, timeout=320
        ).json()
        from yumi.core.features.tts.playback import play_audio
        from yumi.core.features.tts.types import SpeechAudio

        for part in range(int(summary.get("part_count") or 0)):
            audio = connection.request("GET", f"/assistant/voice/{summary['id']}/audio?part={part}", timeout=90)
            mime = audio.headers.get("content-type", "")
            fmt = "mp3" if "mpeg" in mime else "ogg" if "ogg" in mime else "wav"
            play_audio(SpeechAudio(data=audio.content, format=fmt))
    return reply


async def run_client(connection: VoiceConnection, wake: SherpaHeyYumiWake, device: int | None) -> None:
    source = SoundDeviceSource(sample_rate=wake.sample_rate, frame_length=wake.frame_length, device=device)
    collector = UtteranceCollector(sample_rate=wake.sample_rate, frame_length=wake.frame_length)
    vad = _VadBackend(2)

    def is_speech(frame: bytes, sample_rate: int) -> bool:
        window = sample_rate * 30 // 1000 * 2
        return any(vad.is_speech(frame[i : i + window], sample_rate) for i in range(0, len(frame) - window + 1, window))

    print("Listening for Hey Yumi. Press Ctrl+C to stop.")
    source.start()
    collecting = False
    loop = asyncio.get_running_loop()
    try:
        while True:
            frame = await loop.run_in_executor(None, source.read_frame)
            if not collecting:
                if wake.process(frame):
                    collecting = True
                    collector.reset()
                    print("Listening…")
                continue
            utterance = collector.feed(frame, is_speech=is_speech(frame, source.sample_rate))
            if utterance is None:
                continue
            collecting = False
            source.stop()  # avoid recording the spoken reply or a buffered copy of it
            try:
                await asyncio.to_thread(
                    voice_turn, connection, pcm_to_wav_bytes(utterance, sample_rate=source.sample_rate)
                )
            except requests.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 401:
                    raise RuntimeError("Voice device sign-in expired; restart the client to sign in again") from exc
                print(f"Voice turn failed: {exc}")
            except Exception as exc:
                print(f"Voice turn failed: {exc}")
            finally:
                source.start()
                print("Listening for Hey Yumi.")
    finally:
        source.stop()


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


def main(*, mode: str | None, server: str | None, name: str | None, model_dir: str | None,
         keywords_file: str | None, device: int | None, open_browser: bool, logout: bool) -> int:
    if logout:
        logout_nexus()
        print("Voice device credentials removed from this computer.")
        return 0
    mode = mode or choose_mode()
    if not model_dir:
        from yumi.core.features.config import load_model_config

        config = load_model_config()
        model_dir = config.voice_sherpa_model_dir or os.getenv("YUMI_VOICE_MODEL_DIR")
        keywords_file = keywords_file or config.voice_sherpa_keywords_file
    if not model_dir:
        raise SystemExit("Set --voice-model-dir, voice_sherpa_model_dir, or YUMI_VOICE_MODEL_DIR for Hey Yumi.")
    name = name or socket.gethostname() or "Yumi voice"
    wake = SherpaHeyYumiWake(model_dir, keywords_file)
    try:
        connection = connect(mode, server, name, open_browser=open_browser)
        if mode == "local":
            try:
                connection.request("GET", "/assistant", timeout=10)
            except requests.RequestException as exc:
                raise SystemExit(
                    f"Cannot reach local Yumi at {connection.base_url}. Start `yumi --server` first."
                ) from exc
        asyncio.run(run_client(connection, wake, device))
    except KeyboardInterrupt:
        print("\nVoice client stopped.")
    finally:
        wake.close()
    return 0
