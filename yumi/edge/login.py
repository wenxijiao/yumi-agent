"""Nexus browser sign-in for a generated edge workspace (no localhost callback)."""

from __future__ import annotations

import os
import tempfile
import time
import webbrowser
from pathlib import Path
from urllib.parse import urlsplit

import requests


class EdgeLoginError(RuntimeError):
    pass


class _RetryableLoginError(EdgeLoginError):
    pass


def _request(server: str, action: str, body: dict) -> dict:
    try:
        response = requests.post(
            f"{server}/nexus/edge-login/{action}",
            json=body,
            timeout=(5, 20),
            allow_redirects=False,
        )
        if response.status_code == 429:
            if action == "token":
                return {"status": "slow_down", "interval": 5}
            raise EdgeLoginError("Too many sign-in attempts. Please try again later.")
        if response.status_code >= 500:
            raise _RetryableLoginError("The sign-in service is temporarily unavailable. Please retry.")
        if response.status_code != 200:
            if response.status_code == 404:
                raise EdgeLoginError("This server does not support browser sign-in yet. Use a connection code.")
            raise EdgeLoginError("This sign-in request expired or was cancelled. Start again in the terminal.")
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Invalid response")
        return payload
    except requests.RequestException as exc:
        # Response/request objects can carry credentials; never print them.
        raise _RetryableLoginError("Could not reach the sign-in service. Check your connection and retry.") from exc
    except ValueError as exc:
        raise EdgeLoginError("The sign-in service returned an invalid response.") from exc


def save_credentials(env_path: str, *, server: str, edge_name: str, token: str) -> None:
    save_connection(env_path, server=server, edge_name=edge_name, token=token)


def save_connection(
    env_path: str, *, code: str = "", server: str = "", token: str = "", edge_name: str | None = None
) -> None:
    """Atomically replace all transport settings; never carry credentials to a new host."""
    path = Path(env_path)
    if path.is_symlink():
        raise EdgeLoginError("The edge configuration must be a regular file, not a symbolic link.")
    updates = {
        "YUMI_RELAY_URL": server if token else "",
        "YUMI_ACCESS_TOKEN": token,
        "EDGE_LOGIN_NAME": edge_name if token and edge_name else "",
        "YUMI_EDGE_SERVER": server,
        "YUMI_CONNECTION_CODE": code,
        "BRAIN_URL": "",
    }
    if edge_name is not None:
        updates["EDGE_NAME"] = edge_name
    if any("\n" in value or "\r" in value for value in updates.values()):
        raise EdgeLoginError("Invalid connection configuration.")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Do this before replacing credentials: if the workspace isn't writable,
    # leave the current connection intact and cancel the pending sign-in.
    ignore = path.parent / ".gitignore"
    if ignore.is_symlink():
        raise EdgeLoginError("The workspace .gitignore must be a regular file.")
    ignored = ignore.read_text() if ignore.exists() else ""
    missing = [rule for rule in (".env", ".edge-login-*") if rule not in ignored.splitlines()]
    if missing:
        with ignore.open("a") as handle:
            handle.write("\n" + "\n".join(missing) + "\n")
    old = path.read_text() if path.exists() else ""
    lines = [line for line in old.splitlines() if line.split("=", 1)[0].strip() not in updates]
    lines.extend(f"{key}={value}" for key, value in updates.items())
    fd, temporary = tempfile.mkstemp(prefix=".edge-login-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write("\n".join(lines) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def sign_in(
    env_path: str, edge_name: str, *, server: str = "https://api.yumi.nexus", open_browser: bool = True, emit=print
) -> str:
    server = server.rstrip("/")
    parsed = urlsplit(server)
    if (
        (parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}))
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path
        or not parsed.hostname
    ):
        raise EdgeLoginError("Use an HTTPS server address (HTTP is allowed only for localhost development).")
    start = _request(server, "start", {"edge_name": edge_name})
    code, url, device = start.get("user_code"), start.get("verification_uri_complete"), start.get("device_code")
    if not all(isinstance(value, str) and value for value in (code, url, device)):
        raise EdgeLoginError("The server returned an incomplete sign-in request.")
    target = urlsplit(url)
    if target.scheme != "https" or not target.hostname or target.username or target.password:
        raise EdgeLoginError("The server returned an invalid sign-in address.")
    emit(f"Sign in with Yumi to connect {edge_name}.")
    emit(f"Open this link on this computer or another device:\n{url}")
    emit(f"Check that the page shows this code: {code}")
    emit("Waiting for sign-in… Press Ctrl+C to cancel.")
    if open_browser and not (os.getenv("SSH_CONNECTION") or os.getenv("SSH_TTY")):
        try:
            webbrowser.open(url)
        except Exception:
            pass  # The printed URL works on another device, including over SSH.
    deadline = time.monotonic() + min(max(int(start.get("expires_in", 600)), 1), 600)
    interval = max(int(start.get("interval", 5)), 1)
    saved = False
    try:
        while time.monotonic() < deadline:
            time.sleep(min(interval, max(0, deadline - time.monotonic())))
            if time.monotonic() >= deadline:
                break
            try:
                result = _request(server, "token", {"device_code": device})
            except _RetryableLoginError:
                interval = min(30, interval * 2)
                continue
            status = result.get("status")
            if status in {"authorization_pending", "slow_down"}:
                interval = min(30, max(interval + (5 if status == "slow_down" else 0), int(result.get("interval", 5))))
                continue
            token = result.get("access_token")
            if (
                status != "approved"
                or not isinstance(token, str)
                or not token.startswith("yumi_")
                or result.get("edge_name") != edge_name
            ):
                raise EdgeLoginError("The server did not return a valid device connection.")
            try:
                save_credentials(env_path, server=server, edge_name=edge_name, token=token)
            except OSError as exc:
                raise EdgeLoginError(
                    "Could not save the device credentials. Check workspace permissions and retry."
                ) from exc
            saved = True
            try:
                _request(server, "ack", {"device_code": device})
            except EdgeLoginError:
                pass  # Delivery expires server-side; the saved device credential remains valid.
            account = str(result.get("account") or "your Yumi account")
            emit(f"Signed in as {account}. Device credentials saved. Continue registering your tools.")
            return account
        raise EdgeLoginError("Sign-in timed out. Start again when you are ready.")
    finally:
        if not saved:
            try:
                _request(server, "cancel", {"device_code": device})
            except EdgeLoginError:
                pass
