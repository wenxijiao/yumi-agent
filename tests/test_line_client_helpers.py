"""LINE client message helpers (plan-named APIs)."""

from kumi.line.client import (
    flex,
    flex_message,
    text,
    text_message,
    text_with_quick_reply,
)


def test_flex_alias_matches_flex_message():
    b: dict = {"type": "bubble", "body": {"type": "box", "layout": "vertical", "contents": []}}
    assert flex("a", b) == flex_message("a", b)


def test_text_alias_matches_text_message():
    assert text("hi") == text_message("hi")


def test_text_with_quick_reply_builds_items():
    m = text_with_quick_reply(
        "choose",
        [
            {
                "type": "action",
                "action": {"type": "message", "label": "A", "text": "a"},
            }
        ],
    )
    assert m["type"] == "text"
    assert m["text"] == "choose"
    assert m["quickReply"]["items"][0]["action"]["label"] == "A"
