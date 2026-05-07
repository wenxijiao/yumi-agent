"""Incremental parse of ``<think>`` / ``<thinking>`` blocks in model streams."""

import re

# Common "reasoning" wrappers from various chat-tuned models (streaming-safe incremental parse).
_THINK_OPEN = re.compile(r"<(?:redacted_thinking|thinking|think)\b[^>]*>", re.IGNORECASE)
_THINK_CLOSE = re.compile(r"</(?:redacted_thinking|thinking|think)\b[^>]*>", re.IGNORECASE)

# Hold back this many trailing characters max while waiting for a tag to complete.
# Bounded so adversarial input can't grow the buffer indefinitely.
_MAX_PENDING_TAG_BYTES = 256


def _safe_flush_index(buf: str) -> int:
    """Return the largest index up to which ``buf`` can be flushed without
    splitting a possibly-incomplete tag across the chunk boundary.

    If a trailing ``<`` is not yet matched by a ``>``, hold from that ``<``
    so the next chunk can complete the tag. Capped at ``_MAX_PENDING_TAG_BYTES``.
    """
    if not buf:
        return 0
    pos = buf.rfind("<")
    if pos < 0 or ">" in buf[pos:]:
        return len(buf)
    if len(buf) - pos > _MAX_PENDING_TAG_BYTES:
        return len(buf)
    return pos


class ThinkTagParser:
    """Incremental parser that separates model reasoning tags from user-visible text."""

    def __init__(self):
        self._in_think = False
        self._buf = ""

    def feed(self, text: str):
        """Yield ``("thought", content)`` or ``("text", content)`` tuples."""
        self._buf += text
        while self._buf:
            if self._in_think:
                m = _THINK_CLOSE.search(self._buf)
                if m:
                    thought = self._buf[: m.start()]
                    self._buf = self._buf[m.end() :]
                    self._in_think = False
                    if thought:
                        yield ("thought", thought)
                else:
                    flush_to = _safe_flush_index(self._buf)
                    if flush_to == 0:
                        return
                    yield ("thought", self._buf[:flush_to])
                    self._buf = self._buf[flush_to:]
                    return
            else:
                m = _THINK_OPEN.search(self._buf)
                if m:
                    before = self._buf[: m.start()]
                    self._buf = self._buf[m.end() :]
                    self._in_think = True
                    if before:
                        yield ("text", before)
                else:
                    flush_to = _safe_flush_index(self._buf)
                    if flush_to == 0:
                        return
                    yield ("text", self._buf[:flush_to])
                    self._buf = self._buf[flush_to:]
                    return

    def flush(self):
        """Drain whatever is still buffered (called at stream end).

        Anything still in the buffer at end-of-stream is no longer "pending"
        — it will never get a closing ``>``, so flush it as the current state.
        """
        if not self._buf:
            return
        kind = "thought" if self._in_think else "text"
        yield (kind, self._buf)
        self._buf = ""
