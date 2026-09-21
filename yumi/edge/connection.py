"""Choose an edge destination before choosing how to authenticate to it."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from yumi.core.platform.security.auth import _LEGACY_LAN_PREFIXES, LAN_TOKEN_PREFIX
from yumi.core.platform.security.connection import parse_lan_code
from yumi.edge.login import EdgeLoginError, save_connection, sign_in

NEXUS_SERVER = "https://api.yumi.nexus"
LOCAL_SERVER = "http://127.0.0.1:8000"


def read_setting(env_path: str, key: str) -> str:
    path = Path(env_path)
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip().startswith(key + "="):
                value = line.split("=", 1)[1].strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                return value
    return ""


def is_lan(value: str) -> bool:
    return value.startswith((LAN_TOKEN_PREFIX, *_LEGACY_LAN_PREFIXES))


def server_address(value: str) -> tuple[str, str]:
    """Return HTTP base + explicit WebSocket endpoint, usable by every SDK."""
    if is_lan(value):
        value = parse_lan_code(value)
    if any(c.isspace() or ord(c) < 32 for c in value):
        raise EdgeLoginError("Enter a server URL without spaces or control characters.")
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError:
        raise EdgeLoginError("The server port is invalid.") from None
    if (
        parsed.scheme not in {"http", "https", "ws", "wss"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or port == 0
    ):
        raise EdgeLoginError(
            "Use an http://, https://, ws:// or wss:// server URL without credentials or query parameters."
        )
    path = parsed.path.rstrip("/")
    if path.endswith("/ws/edge"):
        path = path[:-8]
    secure = parsed.scheme in {"https", "wss"}
    base = urlunsplit(("https" if secure else "http", parsed.netloc, path, "", ""))
    endpoint = urlunsplit(("wss" if secure else "ws", parsed.netloc, path + "/ws/edge", "", ""))
    return base, endpoint


def configure_connection(
    env_path: str,
    interactive: bool,
    *,
    target: str | None = None,
    method: str | None = None,
    server: str | None = None,
    open_browser: bool = True,
) -> str:
    from yumi.core.features.config.setup_wizard import _framed_prompt, _select_option

    name = read_setting(env_path, "EDGE_NAME") or "my-edge"
    token = read_setting(env_path, "YUMI_ACCESS_TOKEN")
    bound_name = read_setting(env_path, "EDGE_LOGIN_NAME")
    has_saved = bool(
        (not bound_name or bound_name == name)
        if token
        else (read_setting(env_path, "YUMI_CONNECTION_CODE") or read_setting(env_path, "YUMI_EDGE_SERVER"))
    )
    if method == "skip":
        target = "skip"
    if target is None and server is not None:
        target = "nexus" if server.rstrip("/") == NEXUS_SERVER else "server"
    if target is None and method in {"browser", "code"}:
        target = "nexus"
    if target is None and method in {"none", "token"}:
        target = "server"
    if target is None and interactive:
        options = [
            ("nexus", "Yumi Nexus", "Connect to your personal Yumi account"),
            ("server", "Local / custom server", "This computer, your network, or your own server"),
            ("skip", "Set up later", "Create the tool workspace without changing its connection"),
        ]
        if has_saved:
            options.insert(0, ("keep", "Keep the current connection", "Use this workspace's saved configuration"))
        target = _select_option(
            step="Step 3/3: Connection · Destination",
            title="Where should this edge connect?",
            message="",
            options=options,
        )
    if target in {None, "keep", "skip"}:
        return "saved connection (unchanged)" if has_saved else "not set"

    if target == "nexus":
        base = NEXUS_SERVER
        if server is not None and server.rstrip("/") != base:
            raise EdgeLoginError("For a different server, choose --edge-target server.")
        choices = [
            ("browser", "Sign in with Yumi (recommended)", "Open Yumi Identity in your browser"),
            ("code", "Use a connection code", "Paste the code from your Yumi account"),
        ]
        default_method = "browser"
    elif target == "server":
        address = server
        if address is None and interactive:
            address = _framed_prompt(
                "Server address or LAN code",
                step="Step 3/3: Connection · Server",
                title="Connect to your own Yumi server",
                context=f"Enter a URL or the LAN code from `yumi --server`. Default: {LOCAL_SERVER}",
                hint="enter for this computer",
            )
        address = address or LOCAL_SERVER
        base, endpoint = server_address(address)
        choices = [
            ("none", "No sign-in", "Connect directly to a local single-user server"),
            ("token", "Device access token", "Use a credential issued by this server"),
            ("code", "Account connection code", "For a self-hosted multi-user Nexus (Python SDK)"),
            ("browser", "Browser sign-in", "For a Nexus with its own Identity portal configured"),
        ]
        default_method = "none"
    else:
        raise EdgeLoginError("Choose nexus, server or skip as the connection destination.")

    if method is None:
        method = (
            _select_option(
                step="Step 3/3: Connection · Sign-in",
                title="How should this edge connect?" if target == "nexus" else "Does this server require sign-in?",
                message="" if target == "nexus" else "A local single-user Yumi server does not need a Nexus account.",
                options=choices,
            )
            if interactive
            else default_method
        )
    if method not in {choice[0] for choice in choices}:
        raise EdgeLoginError("This sign-in method is not available for the selected destination.")
    if method == "browser":
        account = sign_in(env_path, name, server=base, open_browser=open_browser)
        return f"Signed in as {account}"
    if method == "none":
        # Store the endpoint in the common SDK connection field. Leaving the old
        # EDGE_SERVER/device token set would take priority in some SDKs.
        save_connection(env_path, code=endpoint)
        return f"Direct → {base}"
    if method == "token":
        value = (
            _framed_prompt(
                "Device access token",
                step="Step 3/3: Connection · Credential",
                title="Connect with this server's device credential",
                secret=True,
                context="Use the credential issued by this server. It will be saved only in this workspace.",
            )
            if interactive
            else os.getenv("YUMI_ACCESS_TOKEN", "")
        ).strip()
        if not value:
            raise EdgeLoginError(
                "A device credential is required. In a non-interactive terminal, set YUMI_ACCESS_TOKEN."
            )
        if not value.startswith("yumi_"):
            raise EdgeLoginError("Enter a Yumi device access token issued by this server.")
        save_connection(env_path, server=base, token=value, edge_name=name)
        return f"Device credential → {base}"
    value = (
        _framed_prompt(
            "Connection code",
            step="Step 3/3: Connection · Code",
            title="Connect using your account code",
            secret=True,
            context="Paste the connection code or /link command from your account.",
        )
        if interactive
        else os.getenv("YUMI_CONNECTION_CODE", "")
    ).strip()
    if value.startswith("/link "):
        value = value[6:].strip()
    if not value:
        raise EdgeLoginError("A connection code is required. In a non-interactive terminal, set YUMI_CONNECTION_CODE.")
    if is_lan(value) or value.startswith(("http://", "https://", "ws://", "wss://")):
        raise EdgeLoginError("For a LAN code or server URL, choose Local / custom server and enter it as the address.")
    save_connection(env_path, code=value, server=base)
    return f"Account code → {base}"
