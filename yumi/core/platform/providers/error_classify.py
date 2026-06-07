"""Heuristics for classifying provider errors (e.g. vision/multimodal rejections)."""


def response_status_code(exc: BaseException) -> int | None:
    code = getattr(exc, "status_code", None)
    if code is not None:
        return int(code) if isinstance(code, int) else None
    resp = getattr(exc, "response", None)
    if resp is not None:
        rcode = getattr(resp, "status_code", None)
        if isinstance(rcode, int):
            return rcode
    return None


def exception_text_chain(exc: BaseException, depth: int = 0) -> str:
    """Include ``__cause__`` / ``__context__`` so nested SDK errors still match."""
    parts = [f"{type(exc).__name__} {exc!s}"]
    if depth < 4:
        inner = exc.__cause__ or exc.__context__
        if inner is not None and inner is not exc:
            parts.append(exception_text_chain(inner, depth + 1))
    return " ".join(parts)


def is_multimodal_vision_rejection(exc: BaseException) -> bool:
    """Heuristic: provider rejected the request because of images / multimodal content."""
    text = exception_text_chain(exc).lower()
    phrases = (
        "image_url",
        "multimodal",
        "invalid image",
        "images are not supported",
        "image input",
        "image inputs",
        "unsupported content",
        "cannot accept image",
        "does not accept image",
        "does not support vision",
        "no vision",
        "multimodal inputs",
        "image content",
        "inline image",
        "expected text",
        "only text",
        "vision model",
        "vision.",
    )
    if any(p in text for p in phrases):
        return True
    if "vision" in text and ("model" in text or "api" in text or "support" in text):
        return True
    status = response_status_code(exc)
    if status in (400, 422, 415) and ("image" in text or "multimodal" in text):
        return True
    return False
