"""LINE Messaging API client (HTTP) and webhook signature verification."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

import httpx

_LINE_API = "https://api.line.me/v2/bot"
_MAX_FLEX_BYTES = 50_000


def verify_line_signature(channel_secret: str, body: bytes, x_line_signature: str | None) -> bool:
    """Verify ``X-Line-Signature`` (HMAC-SHA256 of raw body, Base64)."""
    if not channel_secret or not x_line_signature:
        return False
    mac = hmac.new(channel_secret.encode("utf-8"), body, hashlib.sha256).digest()
    expected = base64.b64encode(mac).decode("ascii")
    return hmac.compare_digest(expected, x_line_signature.strip())


def verify_signature(channel_secret: str, body: bytes, x_line_signature: str | None) -> bool:
    """Alias of :func:`verify_line_signature` (plan / SDK naming)."""
    return verify_line_signature(channel_secret, body, x_line_signature)


def flex_message(alt_text: str, contents: dict[str, Any]) -> dict[str, Any]:
    """Build a Flex message dict; shrink or fail-soft if over LINE 50KB limit."""
    msg: dict[str, Any] = {"type": "flex", "altText": alt_text[:400], "contents": contents}
    raw = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    if len(raw) <= _MAX_FLEX_BYTES:
        return msg
    return text_message(alt_text[:400] + " (Flex payload too large; sent as plain text instead.)")


def flex(alt_text: str, contents: dict[str, Any]) -> dict[str, Any]:
    """Alias of :func:`flex_message` (plan naming)."""
    return flex_message(alt_text, contents)


def text_message(text: str, quick_reply: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"type": "text", "text": text[:5000]}
    if quick_reply:
        out["quickReply"] = quick_reply
    return out


def text(text: str, quick_reply: dict[str, Any] | None = None) -> dict[str, Any]:
    """Alias of :func:`text_message` (plan naming)."""
    return text_message(text, quick_reply=quick_reply)


def text_with_quick_reply(text: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    """Text message with LINE ``quickReply`` (max 13 items). *items* are Quick Reply item objects."""
    trimmed = items[:13]
    if not trimmed:
        return text_message(text)
    return text_message(text, quick_reply={"items": trimmed})


class LineMessagingClient:
    """Async LINE Messaging API wrapper."""

    def __init__(self, channel_access_token: str):
        self._token = (channel_access_token or "").strip()
        self._headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    @property
    def token_configured(self) -> bool:
        return bool(self._token)

    async def reply_message(self, reply_token: str, messages: list[dict[str, Any]]) -> None:
        if not self._token or not messages:
            return
        url = f"{_LINE_API}/message/reply"
        payload = {"replyToken": reply_token, "messages": messages[:5]}
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, headers=self._headers, json=payload)
            if r.status_code >= 400:
                raise RuntimeError(f"LINE reply HTTP {r.status_code}: {r.text[:500]}")

    async def push_message(self, to: str, messages: list[dict[str, Any]]) -> None:
        if not self._token or not messages:
            return
        url = f"{_LINE_API}/message/push"
        payload = {"to": to, "messages": messages[:5]}
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, headers=self._headers, json=payload)
            if r.status_code >= 400:
                raise RuntimeError(f"LINE push HTTP {r.status_code}: {r.text[:500]}")

    async def get_message_content(self, message_id: str) -> bytes:
        if not self._token:
            raise RuntimeError("LINE channel access token not configured")
        url = f"{_LINE_API}/message/{message_id}/content"
        timeout = httpx.Timeout(60.0, connect=10.0)
        headers = {"Authorization": f"Bearer {self._token}"}
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(url, headers=headers)
            if r.status_code >= 400:
                raise RuntimeError(f"LINE content HTTP {r.status_code}: {r.text[:300]}")
            return r.content

    async def show_loading_animation(self, chat_id: str, loading_seconds: int = 20) -> None:
        """Best-effort typing indicator (Chat loading)."""
        if not self._token:
            return
        url = f"{_LINE_API}/chat/loading/start"
        payload = {"chatId": chat_id, "loadingSeconds": min(max(loading_seconds, 5), 60)}
        timeout = httpx.Timeout(10.0, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(url, headers=self._headers, json=payload)
            if r.status_code >= 400:
                # API may be unavailable on some plans; ignore
                pass
