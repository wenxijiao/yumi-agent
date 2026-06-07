"""Pure helpers in providers/diagnostics: text shortening and payload summaries.

These build the redacted/truncated snapshots written to failure diagnostics, so
they must stay stable and never raise on odd inputs.
"""

from yumi.core.platform.providers.diagnostics import (
    provider_name,
    short_text,
    summarize_openai_message,
    summarize_tools,
)

# ── short_text ──


def test_short_text_none_is_empty():
    assert short_text(None) == ""


def test_short_text_passes_short_string_through():
    assert short_text("hello") == "hello"


def test_short_text_serializes_non_strings():
    assert short_text({"a": 1}) == '{"a": 1}'


def test_short_text_truncates_with_marker():
    out = short_text("x" * 600, limit=500)
    assert out.startswith("x" * 500)
    assert "truncated 100 chars" in out


def test_short_text_falls_back_to_str_for_unserializable():
    class Weird:
        def __repr__(self):
            return "WEIRD"

    # default=str makes json.dumps succeed, so we still get a string, never raise
    assert isinstance(short_text(Weird()), str)


# ── summarize_openai_message ──


def test_summarize_message_basic_fields():
    out = summarize_openai_message({"role": "user", "content": "hi", "name": "bob"})
    assert out["role"] == "user"
    assert out["content_type"] == "str"
    assert out["content_preview"] == "hi"
    assert out["name"] == "bob"


def test_summarize_message_without_name_omits_it():
    out = summarize_openai_message({"role": "assistant", "content": "ok"})
    assert "name" not in out


def test_summarize_message_summarizes_tool_calls():
    msg = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "function": {"name": "do_thing", "arguments": '{"x":1}'},
                "thoughtSignature": "abc",
            }
        ],
    }
    out = summarize_openai_message(msg)
    tc = out["tool_calls"][0]
    assert tc["id"] == "call_1"
    assert tc["name"] == "do_thing"
    assert tc["arguments_preview"] == '{"x":1}'
    assert tc["has_thought_signature"] is True


# ── summarize_tools ──


def test_summarize_tools_extracts_name_and_params():
    tools = [
        {
            "function": {
                "name": "lookup",
                "description": "find a thing",
                "parameters": {"properties": {"q": {}, "limit": {}}},
            }
        }
    ]
    out = summarize_tools(tools)
    assert out[0]["name"] == "lookup"
    assert out[0]["description_preview"] == "find a thing"
    assert out[0]["parameter_names"] == ["q", "limit"]


def test_summarize_tools_handles_none_and_empty():
    assert summarize_tools(None) == []
    assert summarize_tools([]) == []


# ── provider_name ──


def test_provider_name_strips_suffix_and_lowercases():
    class OpenAIProvider:
        pass

    assert provider_name(OpenAIProvider()) == "openai"


def test_provider_name_none_is_unknown():
    assert provider_name(None) == "unknown"
