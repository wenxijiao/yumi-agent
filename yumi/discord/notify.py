"""Server-side Discord outbound: timer completions without a /timer-events client.

Outbound push is done over Discord's REST API (not the gateway) so it stays
stateless and works inside the API process, exactly like the Telegram
``sendMessage`` path. Yumi sessions are named ``dc_<user_id>``; we open (or
reuse) a DM channel for that user, then POST the message into it.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from yumi.core.features.config import get_discord_bot_token

logger = logging.getLogger(__name__)

_DC_SESSION = re.compile(r"^dc_(\d+)$")
_DISCORD_API = "https://discord.com/api/v10"
_MAX_MESSAGE = 2000


def parse_discord_user_id(session_id: str) -> int | None:
    """Map Yumi session ``dc_<user_id>`` to a Discord user id."""
    m = _DC_SESSION.match(session_id.strip())
    if not m:
        return None
    return int(m.group(1))


def _events_to_plain_text(events: list[dict[str, Any]]) -> str:
    return "".join(str(e.get("content", "")) for e in events if e.get("type") == "text").strip()


def _chunk_message(text: str) -> list[str]:
    if not text:
        return []
    if len(text) <= _MAX_MESSAGE:
        return [text]
    out: list[str] = []
    rest = text
    while rest:
        out.append(rest[:_MAX_MESSAGE])
        rest = rest[_MAX_MESSAGE:]
    return out


async def send_timer_result_to_discord(
    session_id: str,
    description: str,
    events: list[dict[str, Any]],
) -> None:
    """If session is ``dc_*`` and bot token is set, DM the timer result to Discord."""
    user_id = parse_discord_user_id(session_id)
    if user_id is None:
        return

    token = get_discord_bot_token()
    if not token:
        logger.info(
            "Discord timer notify skipped: no bot token in this API process. "
            "On the machine running `yumi --server`, set DISCORD_BOT_TOKEN or "
            "discord_bot_token in ~/.yumi/config.json (same machine as the API)."
        )
        return

    body = _events_to_plain_text(events)
    if not body:
        errs = [str(e.get("content", "")) for e in events if e.get("type") == "error"]
        if errs:
            body = "Error: " + errs[0]
        else:
            body = f"[Timer] {description}"

    await send_text_to_discord(session_id, "⏰ " + body)


async def _open_dm_channel(client: httpx.AsyncClient, token: str, user_id: int) -> str | None:
    """Open (or reuse) a DM channel with ``user_id`` and return its channel id."""
    try:
        r = await client.post(
            f"{_DISCORD_API}/users/@me/channels",
            headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
            json={"recipient_id": str(user_id)},
        )
    except Exception as exc:
        logger.warning("Discord open DM error: %s", exc)
        return None
    if r.status_code >= 400:
        logger.warning("Discord open DM HTTP %s: %s", r.status_code, r.text[:400])
        return None
    try:
        return str(r.json().get("id") or "") or None
    except Exception:
        return None


async def send_text_to_discord(session_id: str, text: str, *, prefix: str = "") -> bool:
    """Send arbitrary text to a Discord session via the REST API."""
    chunks = _chunk_message(text)
    if not chunks:
        return False
    if prefix:
        chunks[0] = f"[{prefix}] {chunks[0]}"

    user_id = parse_discord_user_id(session_id)
    if user_id is None:
        return False
    token = get_discord_bot_token()
    if not token:
        logger.info(
            "Discord proactive send skipped: no bot token in this API process. "
            "Set DISCORD_BOT_TOKEN or discord_bot_token in ~/.yumi/config.json."
        )
        return False

    timeout = httpx.Timeout(20.0, connect=10.0)
    sent_any = False
    async with httpx.AsyncClient(timeout=timeout) as client:
        channel_id = await _open_dm_channel(client, token, user_id)
        if not channel_id:
            return False
        for part in chunks:
            try:
                r = await client.post(
                    f"{_DISCORD_API}/channels/{channel_id}/messages",
                    headers={"Authorization": f"Bot {token}", "Content-Type": "application/json"},
                    json={"content": part},
                )
                if r.status_code >= 400:
                    logger.warning(
                        "Discord create message HTTP %s: %s",
                        r.status_code,
                        r.text[:400],
                    )
                    continue
                logger.info("Discord message sent to user_id=%s", user_id)
                sent_any = True
            except Exception as exc:
                logger.warning("Discord create message error: %s", exc)
    return sent_any
