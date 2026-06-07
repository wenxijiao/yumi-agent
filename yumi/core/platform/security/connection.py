"""LAN-only connection helpers.

Relay profile bootstrap (StoredProfile / bootstrap_profile / saved profile
selection) lives in the enterprise package — OSS only ships direct LAN
connection configuration.
"""

from __future__ import annotations

import os
import socket
from ipaddress import ip_address
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel
from yumi.core.platform.security.auth import YumiLanCode, decode_lan_code, encode_lan_code

DEFAULT_LOCAL_SERVER_URL = "http://127.0.0.1:8000"
DEFAULT_LOCAL_EDGE_URL = "ws://127.0.0.1:8000/ws/edge"


class ConnectionConfig(BaseModel):
    mode: Literal["direct"]
    scope: Literal["chat", "ui", "edge"]
    base_url: str
    access_token: str | None = None

    def auth_headers(self) -> dict[str, str]:
        if not self.access_token:
            return {}
        return {"Authorization": f"Bearer {self.access_token}"}

    def relay_edge_ws_url(self) -> str:
        return http_to_ws(self.base_url.rstrip("/")) + "/ws/edge"


def http_to_ws(url: str) -> str:
    if url.startswith("https://"):
        return "wss://" + url[len("https://") :]
    if url.startswith("http://"):
        return "ws://" + url[len("http://") :]
    return url


def _is_usable_lan_ip(address: str) -> bool:
    try:
        parsed = ip_address(address)
    except ValueError:
        return False

    if parsed.version != 4:
        return False

    if parsed.is_loopback or parsed.is_link_local or parsed.is_unspecified:
        return False

    return True


def discover_lan_ips() -> list[str]:
    candidates: list[str] = []

    def add_candidate(address: str) -> None:
        if _is_usable_lan_ip(address) and address not in candidates:
            candidates.append(address)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            add_candidate(sock.getsockname()[0])
    except OSError:
        pass

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM):
            add_candidate(info[4][0])
    except socket.gaierror:
        pass

    return candidates


def build_lan_server_url(host: str, port: int = 8000) -> str:
    return f"http://{host}:{port}"


def issue_lan_code(base_url: str, expires_at: int = 0, secret: str | None = None) -> str:
    parsed = urlparse(base_url.rstrip("/"))
    if not parsed.hostname:
        raise ValueError("LAN server URL must include a host.")

    code = YumiLanCode(
        host=parsed.hostname,
        port=parsed.port or 8000,
        expires_at=expires_at,
    )
    return encode_lan_code(code, secret=secret)


def parse_lan_code(code: str, secret: str | None = None) -> str:
    lan_code = decode_lan_code(code, secret=secret)
    return build_lan_server_url(lan_code.host, lan_code.port)


def resolve_connection_config(scope: Literal["chat", "ui", "edge"]) -> ConnectionConfig:
    if scope == "edge":
        return ConnectionConfig(
            mode="direct",
            scope=scope,
            base_url=os.getenv("BRAIN_URL", DEFAULT_LOCAL_EDGE_URL),
        )

    return ConnectionConfig(
        mode="direct",
        scope=scope,
        base_url=os.getenv("YUMI_SERVER_URL", DEFAULT_LOCAL_SERVER_URL),
    )
