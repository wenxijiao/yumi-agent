"""LINE Flex builders: structure, size, postback protocol."""

import json

from yumi.line.flex_builders import (
    file_upload_receipt,
    flex_size_bytes,
    format_postback,
    model_card,
    model_picker_carousel,
    parse_postback,
    timer_done_card,
    tool_confirm_card,
    usage_carousel,
)


def test_parse_postback_roundtrip():
    s = format_postback("tool_confirm", "a1b2c3d4", "allow")
    assert parse_postback(s) == ("tool_confirm", "a1b2c3d4", "allow")


def test_tool_confirm_card_shape():
    bubble = tool_confirm_card("echo", '{"x": 1}', "abcd1234")
    assert bubble["type"] == "bubble"
    assert bubble["body"]["type"] == "box"
    foot = bubble["footer"]["contents"]
    assert any(b.get("type") == "button" and b.get("action", {}).get("type") == "postback" for b in foot[-1:])


def test_flex_messages_under_50kb():
    rows = [
        {
            "user_id": "u_test",
            "day": "2025-01-01",
            "model": "gpt-4o",
            "kind": "chat",
            "prompt_tokens": 1,
            "completion_tokens": 2,
            "est_usd": 0.001,
        }
    ]
    assert flex_size_bytes(usage_carousel(rows, 0, False, "sess1")) < 50_000
    assert flex_size_bytes(model_card("p", "m", "e", "em", "sid")) < 50_000
    assert flex_size_bytes(model_picker_carousel(["a", "b"], "sid")) < 50_000
    assert flex_size_bytes(timer_done_card("d", "body", "t1")) < 50_000
    assert flex_size_bytes(file_upload_receipt("f.txt", 1024)) < 50_000


def test_postback_data_prefix():
    bubble = tool_confirm_card("t", "{}", "ab12cd34")
    foot = bubble["footer"]["contents"]
    actions: list[str] = []

    def collect(obj):
        if isinstance(obj, dict):
            if obj.get("type") == "button":
                act = obj.get("action") or {}
                if act.get("type") == "postback":
                    actions.append(str(act.get("data", "")))
            for v in obj.values():
                collect(v)
        elif isinstance(obj, list):
            for x in obj:
                collect(x)

    collect(foot)
    for d in actions:
        assert d.startswith("yumi|tool_confirm|")
        parsed = parse_postback(d)
        assert parsed is not None


def test_json_serialize_flex_contents():
    bubble = tool_confirm_card("x", "y", "12345678")
    json.dumps(bubble, ensure_ascii=False)
