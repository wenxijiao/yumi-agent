"""Unparseable tool-call arguments are dropped (so the model is asked to retry)."""

from yumi.core.platform.tools.normalize import normalize_tool_calls


def test_unrepairable_args_drop_the_call():
    # valid name + arguments that even json-repair can't recover -> dropped, so
    # normalize returns []; the dispatch normalizer then asks the model to retry
    # instead of running the tool with empty {} args.
    assert normalize_tool_calls([{"function": {"name": "do_thing", "arguments": "not json at all"}}]) == []


def test_valid_args_are_kept():
    out = normalize_tool_calls([{"function": {"name": "do_thing", "arguments": '{"x": 1}'}}])
    assert out and out[0]["function"]["arguments"] == {"x": 1}


def test_truncated_json_is_repaired_not_dropped():
    out = normalize_tool_calls([{"function": {"name": "do_thing", "arguments": '{"location": "Auckl'}}])
    assert out and out[0]["function"]["arguments"] == {"location": "Auckl"}


def test_legitimately_empty_args_stay_empty():
    # a no-arg tool call (empty/absent arguments) must NOT be dropped
    out = normalize_tool_calls([{"function": {"name": "do_thing", "arguments": ""}}])
    assert out and out[0]["function"]["arguments"] == {}
