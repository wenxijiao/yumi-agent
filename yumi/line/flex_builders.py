"""LINE Flex Message builders and compact postback protocol.

Postback ``data`` max 300 chars: ``yumi|<verb>|<short_id>|<arg>``
"""

from __future__ import annotations

import json
from typing import Any

POSTBACK_PREFIX = "yumi"
MAX_POSTBACK_LEN = 300

# Compact postback verbs: ``yumi|<verb>|<short_id>|<arg>`` (LINE data <= 300 chars).
POSTBACK_VERB_TOOL_CONFIRM = "tool_confirm"
POSTBACK_VERB_MODEL_SWITCH = "model_switch"
POSTBACK_VERB_TIMER_SNOOZE = "timer_snooze"
POSTBACK_VERB_TIMER_RERUN = "timer_rerun"
POSTBACK_VERB_USAGE_PAGE = "usage_page"

MODEL_SWITCH_ARG_OPEN = "__open__"


def format_postback(verb: str, short_id: str, arg: str) -> str:
    short_id = short_id[:16]
    arg = arg[:200]
    s = f"{POSTBACK_PREFIX}|{verb}|{short_id}|{arg}"
    if len(s) > MAX_POSTBACK_LEN:
        raise ValueError(f"postback data too long ({len(s)} > {MAX_POSTBACK_LEN})")
    return s


def parse_postback(data: str) -> tuple[str, str, str] | None:
    if not data or not data.startswith(f"{POSTBACK_PREFIX}|"):
        return None
    rest = data[len(POSTBACK_PREFIX) + 1 :]
    parts = rest.split("|", 2)
    if len(parts) != 3:
        return None
    verb, short_id, arg = parts[0], parts[1], parts[2]
    if not verb or not short_id:
        return None
    return verb, short_id, arg


def _text_block(text: str, *, size: str = "sm", wrap: bool = True, weight: str | None = None) -> dict[str, Any]:
    t: dict[str, Any] = {"type": "text", "text": text[:2000], "size": size, "wrap": wrap}
    if weight:
        t["weight"] = weight
    return t


def _postback_button(label: str, data: str, style: str | None = None) -> dict[str, Any]:
    btn: dict[str, Any] = {
        "type": "button",
        "style": style or "primary",
        "height": "sm",
        "action": {"type": "postback", "label": label[:20], "data": data},
    }
    return btn


def _uri_button(label: str, uri: str) -> dict[str, Any]:
    return {
        "type": "button",
        "style": "link",
        "height": "sm",
        "action": {"type": "uri", "label": label[:20], "uri": uri[:1000]},
    }


def tool_confirm_card(tool_name: str, arguments_preview: str, short_id: str) -> dict[str, Any]:
    lines = (arguments_preview or "").splitlines()[:12]
    body_text = "\n".join(lines) if lines else "(no arguments)"
    deny = format_postback(POSTBACK_VERB_TOOL_CONFIRM, short_id, "deny")
    allow = format_postback(POSTBACK_VERB_TOOL_CONFIRM, short_id, "allow")
    always = format_postback(POSTBACK_VERB_TOOL_CONFIRM, short_id, "always")
    return {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                _text_block("Tool Confirmation", size="md", weight="bold"),
            ],
            "backgroundColor": "#FF5555",
            "paddingAll": "12px",
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                _text_block(f"Tool: {tool_name[:200]}", weight="bold"),
                _text_block(body_text[:3500], size="xs"),
            ],
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "spacing": "sm",
                    "contents": [
                        _postback_button("Deny", deny, "secondary"),
                        _postback_button("Allow", allow, "primary"),
                    ],
                },
                _postback_button("Always allow", always, "secondary"),
            ],
        },
    }


def model_card(
    chat_provider: str,
    chat_model: str,
    embed_provider: str,
    embed_model: str,
    switch_session_id: str,
) -> dict[str, Any]:
    """Footer opens model picker carousel via postback ``__open__``."""
    open_pb = format_postback(POSTBACK_VERB_MODEL_SWITCH, switch_session_id, MODEL_SWITCH_ARG_OPEN)
    return {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                _text_block("Model configuration", weight="bold"),
                _text_block(f"Chat: {chat_provider} / {chat_model}", size="sm"),
                _text_block(f"Embed: {embed_provider} / {embed_model}", size="sm"),
            ],
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "contents": [_postback_button("Switch chat model", open_pb, "primary")],
        },
    }


def model_picker_carousel(candidates: list[str], pick_session_id: str) -> dict[str, Any]:
    """One bubble per candidate model; postback carries index."""
    bubbles: list[dict[str, Any]] = []
    for i, name in enumerate(candidates[:10]):
        pb = format_postback(POSTBACK_VERB_MODEL_SWITCH, pick_session_id, str(i))
        bubbles.append(
            {
                "type": "bubble",
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [
                        _text_block(name[:80], weight="bold"),
                        _postback_button("Select", pb, "primary"),
                    ],
                },
            }
        )
    if not bubbles:
        bubbles.append(
            {
                "type": "bubble",
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [_text_block("No candidate models", weight="bold")],
                },
            }
        )
    return {"type": "carousel", "contents": bubbles}


def usage_carousel(
    rows: list[dict[str, Any]],
    page: int,
    has_next: bool,
    page_session_id: str,
) -> dict[str, Any]:
    """Each row: user_id, day, model, kind, prompt_tokens, completion_tokens, est_usd."""
    bubbles: list[dict[str, Any]] = []
    for r in rows[:10]:
        uid = str(r.get("user_id", ""))[:32]
        day = str(r.get("day", ""))
        model = str(r.get("model", ""))[:24]
        kind = str(r.get("kind", ""))
        pt = int(r.get("prompt_tokens", 0))
        ct = int(r.get("completion_tokens", 0))
        est = float(r.get("est_usd", 0.0))
        bubbles.append(
            {
                "type": "bubble",
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "spacing": "xs",
                    "contents": [
                        _text_block(f"{uid}", weight="bold", size="xs"),
                        _text_block(f"{day} · {model} · {kind}", size="xs"),
                        _text_block(f"tokens in+out: {pt}+{ct}", size="xs"),
                        _text_block(f"~USD {est:.6f}", size="xs"),
                    ],
                },
            }
        )
    if not bubbles:
        bubbles.append(
            {
                "type": "bubble",
                "body": {
                    "type": "box",
                    "layout": "vertical",
                    "contents": [_text_block("No usage rows", weight="bold")],
                },
            }
        )
    nav_contents: list[dict[str, Any]] = [
        _text_block(f"Usage page {page}", weight="bold"),
    ]
    if has_next:
        next_pb = format_postback(POSTBACK_VERB_USAGE_PAGE, page_session_id, str(page + 1))
        nav_contents.append(_postback_button("Next page", next_pb, "primary"))
    bubbles.append(
        {
            "type": "bubble",
            "body": {"type": "box", "layout": "vertical", "contents": nav_contents},
        }
    )
    return {"type": "carousel", "contents": bubbles}


def timer_done_card(description: str, body_text: str, short_id: str) -> dict[str, Any]:
    snooze = format_postback(POSTBACK_VERB_TIMER_SNOOZE, short_id, "300")
    rerun = format_postback(POSTBACK_VERB_TIMER_RERUN, short_id, "1")
    excerpt = (body_text or "")[:1200]
    return {
        "type": "bubble",
        "header": {
            "type": "box",
            "layout": "vertical",
            "contents": [_text_block("Timer", size="lg", weight="bold")],
            "paddingAll": "10px",
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                _text_block(f"⏰ {description[:500]}", weight="bold"),
                _text_block(excerpt, size="xs"),
            ],
        },
        "footer": {
            "type": "box",
            "layout": "vertical",
            "spacing": "sm",
            "contents": [
                {
                    "type": "box",
                    "layout": "horizontal",
                    "spacing": "sm",
                    "contents": [
                        _postback_button("Snooze 5m", snooze, "secondary"),
                        _postback_button("Re-run", rerun, "primary"),
                    ],
                },
            ],
        },
    }


def file_upload_receipt(
    name: str,
    size_bytes: int,
    open_uri: str | None = None,
    *,
    thumbnail_url: str | None = None,
) -> dict[str, Any]:
    size_kb = max(1, size_bytes // 1024) if size_bytes else 0
    contents: list[dict[str, Any]] = [
        _text_block("File saved", weight="bold"),
        _text_block(f"{name[:200]}", size="sm"),
        _text_block(f"Size: ~{size_kb} KB", size="xs"),
    ]
    footer: dict[str, Any] | None = None
    if open_uri and open_uri.startswith(("http://", "https://")):
        footer = {
            "type": "box",
            "layout": "vertical",
            "contents": [_uri_button("Open", open_uri)],
        }
    bubble: dict[str, Any] = {
        "type": "bubble",
        "body": {"type": "box", "layout": "vertical", "spacing": "sm", "contents": contents},
    }
    if thumbnail_url and thumbnail_url.startswith(("http://", "https://")):
        bubble["hero"] = {
            "type": "image",
            "url": thumbnail_url[:1000],
            "size": "full",
            "aspectRatio": "20:13",
            "aspectMode": "cover",
        }
    if footer:
        bubble["footer"] = footer
    return bubble


def flex_size_bytes(contents: dict[str, Any], alt_text: str = ".") -> int:
    from yumi.line.client import flex_message

    msg = flex_message(alt_text, contents)
    return len(json.dumps(msg, ensure_ascii=False).encode("utf-8"))
