"""Heuristics for multimodal API rejection → text-only retry."""

from kumi.core.features.prompts.composer import messages_have_multimodal_images as _messages_have_multimodal_images
from kumi.core.platform.providers.error_classify import (
    is_multimodal_vision_rejection as _is_multimodal_vision_rejection,
)


def test_multimodal_rejection_openai_style():
    class E(Exception):
        status_code = 400

    exc = E("Error code: 400 - {'message': 'Invalid image_url: ...'}")
    assert _is_multimodal_vision_rejection(exc) is True


def test_multimodal_rejection_ollama_style():
    exc = Exception('model "llama3" does not support vision')
    assert _is_multimodal_vision_rejection(exc) is True


def test_not_multimodal_rejection():
    exc = Exception("rate limit exceeded")
    assert _is_multimodal_vision_rejection(exc) is False


def test_messages_have_multimodal_images():
    msgs = [
        {"role": "user", "content": [{"type": "text", "text": "hi"}, {"type": "image_url", "image_url": {}}]},
    ]
    assert _messages_have_multimodal_images(msgs) is True
    assert _messages_have_multimodal_images([{"role": "user", "content": "plain"}]) is False
