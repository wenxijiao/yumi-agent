"""Pydantic API schema validation."""

from kumi.core.api.schemas import ChatRequest, ModelConfigUpdateRequest, TranscribeRequest


def test_chat_request_defaults():
    r = ChatRequest(prompt="hi")
    assert r.session_id == "default"
    assert r.think is False


def test_model_config_update_optional_fields():
    r = ModelConfigUpdateRequest()
    assert r.chat_provider is None
    assert r.memory_max_recent_messages is None
    assert r.stt_provider is None


def test_transcribe_request_defaults():
    r = TranscribeRequest(filename="voice.ogg", content_base64="YWJj")
    assert r.session_id == "default"
    assert r.language is None
