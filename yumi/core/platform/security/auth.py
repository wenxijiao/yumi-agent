"""LAN code primitives.

The core Yumi server only deals in LAN access codes (host + optional HMAC)
and stays focused on the local-area-network experience.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from urllib.parse import urlparse

from pydantic import BaseModel

LAN_TOKEN_PREFIX = "yumi-lan_"
_LEGACY_LAN_PREFIXES = ("ml1_", "yumi_lan_")


class YumiLanCode(BaseModel):
    version: int = 1
    host: str
    port: int = 8000
    expires_at: int = 0


def unix_timestamp() -> int:
    return int(time.time())


def _lan_hmac(data_bytes: bytes, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        data_bytes,
        hashlib.sha256,
    ).hexdigest()[:16]


def encode_lan_code(code: YumiLanCode, secret: str | None = None) -> str:
    """Encode a LAN *connection string* — NOT an auth credential.

    The token carries the server host/port (+ optional expiry) so a client knows
    where to connect. When *secret* (``lan_secret``) is given, an HMAC ``s`` field
    is added; that only provides tamper-detection, and only when the decoding side
    also holds the same secret (see :func:`decode_lan_code`). Possession of the
    code does not by itself grant access — the OSS server has no auth, so anyone
    who can reach the host/port can connect. Treat the code as a convenience URL,
    not a secret.
    """
    payload_dict = {
        "v": code.version,
        "h": code.host,
        "p": code.port,
        **({"x": code.expires_at} if code.expires_at else {}),
    }
    payload_bytes = json.dumps(
        payload_dict,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    if secret:
        sig = _lan_hmac(payload_bytes, secret)
        payload_dict["s"] = sig
        payload_bytes = json.dumps(
            payload_dict,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    encoded = base64.urlsafe_b64encode(payload_bytes).decode("utf-8").rstrip("=")
    return f"{LAN_TOKEN_PREFIX}{encoded}"


def decode_lan_code(token: str, secret: str | None = None) -> YumiLanCode:
    """Decode a LAN connection string into host/port.

    Signature verification is best-effort: it only happens when BOTH *secret* is
    supplied AND the token carries an ``s`` field. With no shared secret the
    signature is not checked — so the HMAC is an integrity aid, not an
    authentication mechanism. See :func:`encode_lan_code`.
    """
    if token.startswith(LAN_TOKEN_PREFIX):
        encoded = token[len(LAN_TOKEN_PREFIX) :]
    else:
        matched = False
        encoded = ""
        for prefix in _LEGACY_LAN_PREFIXES:
            if token.startswith(prefix):
                encoded = token[len(prefix) :]
                matched = True
                break
        if not matched:
            raise ValueError("Invalid Yumi LAN code prefix.")

    padding = "=" * (-len(encoded) % 4)
    payload = base64.urlsafe_b64decode(encoded + padding)
    data = json.loads(payload.decode("utf-8"))

    if "h" in data:
        code = YumiLanCode(
            version=int(data.get("v", 1)),
            host=str(data["h"]),
            port=int(data.get("p", 8000)),
            expires_at=int(data.get("x", 0)),
        )
    else:
        base_url = data.get("base_url", "")
        parsed = urlparse(base_url)
        if not parsed.hostname:
            raise ValueError("Yumi LAN code is missing a valid host.")
        code = YumiLanCode(
            version=int(data.get("version", 1)),
            host=parsed.hostname,
            port=parsed.port or 8000,
            expires_at=int(data.get("expires_at", 0)),
        )

    if code.expires_at and code.expires_at < unix_timestamp():
        raise ValueError("Yumi LAN code has expired.")

    if secret and "s" in data:
        verify_dict = {k: v for k, v in data.items() if k != "s"}
        verify_bytes = json.dumps(
            verify_dict,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        expected = _lan_hmac(verify_bytes, secret)
        if not hmac.compare_digest(expected, data["s"]):
            raise ValueError("Yumi LAN code signature is invalid (tampered?).")

    return code
