"""Server-side LINE outbound: timer completions (Flex card + push)."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from kumi.core.config.line import get_line_channel_access_token, line_push_disabled
from kumi.line.client import LineMessagingClient, flex_message, text_message
from kumi.line.flex_builders import timer_done_card
from kumi.line.pending import register_timer_card_context

logger = logging.getLogger(__name__)


def client_session_from_qualified(qualified_session_id: str) -> str:
    s = (qualified_session_id or "").strip()
    if "__" in s:
        return s.split("__", 1)[1]
    return s


def line_push_recipient_user_id(session_id: str) -> str | None:
    """Map storage session to LINE user id (``U...``) for ``push`` ``to`` field."""
    raw = client_session_from_qualified(session_id)
    if raw.startswith("line_"):
        rest = raw[5:].strip()
        return rest if rest else None
    return None


def _events_to_plain_text(events: list[dict[str, Any]]) -> str:
    return "".join(str(e.get("content", "")) for e in events if e.get("type") == "text").strip()


async def send_timer_result_to_line(
    session_id: str,
    description: str,
    events: list[dict[str, Any]],
) -> None:
    to_uid = line_push_recipient_user_id(session_id)
    if not to_uid:
        return
    if line_push_disabled():
        logger.info("LINE timer notify skipped: LINE_DISABLE_PUSH is set.")
        return
    token = get_line_channel_access_token()
    if not token:
        logger.info(
            "LINE timer notify skipped: no channel access token. "
            "Set LINE_CHANNEL_ACCESS_TOKEN or line_channel_access_token in config."
        )
        return

    body = _events_to_plain_text(events)
    if not body:
        errs = [str(e.get("content", "")) for e in events if e.get("type") == "error"]
        if errs:
            body = "Error: " + errs[0]
        else:
            body = f"[Timer] {description}"

    short_id = uuid.uuid4().hex[:8]
    register_timer_card_context(
        short_id,
        {
            "description": description,
            "qualified_session_id": session_id,
            "client_session_id": client_session_from_qualified(session_id),
        },
    )
    bubble = timer_done_card(description, body, short_id)
    msg = flex_message("Timer", bubble)

    client = LineMessagingClient(token)
    try:
        await client.push_message(to_uid, [msg])
        logger.info("LINE timer Flex message sent to userId=%s", to_uid)
    except Exception as exc:
        logger.warning("LINE timer push failed (%s); falling back to text.", exc)
        try:
            await client.push_message(
                to_uid,
                [text_message("⏰ " + body[:4800])],
            )
        except Exception as exc2:
            logger.warning("LINE timer text push error: %s", exc2)
