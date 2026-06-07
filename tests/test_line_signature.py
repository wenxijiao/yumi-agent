"""LINE webhook HMAC signature verification."""

import base64
import hashlib
import hmac

from yumi.line.client import verify_line_signature, verify_signature


def test_verify_line_signature_ok():
    secret = "channelsecret"
    body = b'{"events":[]}'
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).digest()
    sig = base64.b64encode(mac).decode("ascii")
    assert verify_line_signature(secret, body, sig) is True
    assert verify_signature(secret, body, sig) is True


def test_verify_line_signature_rejects_bad():
    secret = "channelsecret"
    body = b'{"events":[]}'
    assert verify_line_signature(secret, body, "AAAA") is False
    assert verify_line_signature(secret, body, None) is False
    assert verify_line_signature("", body, "x") is False
