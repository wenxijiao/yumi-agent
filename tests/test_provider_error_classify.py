"""Unit tests for provider error classification heuristics.

Pure logic, no network — covers the path every chat turn relies on to decide
whether a provider failure was a vision/multimodal rejection (so the caller can
retry text-only) versus a generic error.
"""

from yumi.core.platform.providers.error_classify import (
    exception_text_chain,
    is_multimodal_vision_rejection,
    response_status_code,
)


class _WithStatus(Exception):
    def __init__(self, msg, status_code=None):
        super().__init__(msg)
        self.status_code = status_code


class _Resp:
    def __init__(self, status_code):
        self.status_code = status_code


class _WithResponse(Exception):
    def __init__(self, msg, status_code):
        super().__init__(msg)
        self.response = _Resp(status_code)


# ── response_status_code ──


def test_status_code_from_direct_attribute():
    assert response_status_code(_WithStatus("boom", status_code=400)) == 400


def test_status_code_from_response_attribute():
    assert response_status_code(_WithResponse("boom", 422)) == 422


def test_status_code_absent_returns_none():
    assert response_status_code(ValueError("plain")) is None


def test_status_code_non_int_returns_none():
    assert response_status_code(_WithStatus("boom", status_code="400")) is None


# ── exception_text_chain ──


def test_text_chain_includes_type_and_message():
    text = exception_text_chain(ValueError("bad image_url"))
    assert "ValueError" in text
    assert "bad image_url" in text


def test_text_chain_follows_cause():
    inner = ValueError("images are not supported")
    try:
        raise RuntimeError("wrapper") from inner
    except RuntimeError as exc:
        text = exception_text_chain(exc)
    assert "wrapper" in text
    assert "images are not supported" in text


def test_text_chain_depth_is_bounded():
    # A long __context__ chain must terminate (depth cap) without recursing forever.
    exc = ValueError("level0")
    for i in range(1, 10):
        nxt = ValueError(f"level{i}")
        nxt.__context__ = exc
        exc = nxt
    text = exception_text_chain(exc)  # should not raise / hang
    assert "level9" in text


# ── is_multimodal_vision_rejection ──


def test_phrase_match_detects_rejection():
    assert is_multimodal_vision_rejection(ValueError("Error: images are not supported by this model"))


def test_vision_plus_model_detects_rejection():
    assert is_multimodal_vision_rejection(ValueError("this vision model is unavailable"))


def test_status_plus_image_detects_rejection():
    assert is_multimodal_vision_rejection(_WithStatus("bad image payload", status_code=400))


def test_nested_cause_detects_rejection():
    inner = ValueError("image_url not accepted")
    try:
        raise RuntimeError("request failed") from inner
    except RuntimeError as exc:
        assert is_multimodal_vision_rejection(exc)


def test_generic_error_is_not_a_rejection():
    assert not is_multimodal_vision_rejection(ValueError("connection reset by peer"))


def test_status_without_image_keyword_is_not_a_rejection():
    assert not is_multimodal_vision_rejection(_WithStatus("rate limited", status_code=400))
