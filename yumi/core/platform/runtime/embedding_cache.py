"""Bounded in-memory vector reuse for one chat request, including worker threads."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from concurrent.futures import Future
from contextvars import ContextVar
from threading import Lock


class RequestEmbeddingCache:
    def __init__(self) -> None:
        self._lock = Lock()
        self._entries: dict[tuple[str, int, str, bytes], Future[list[float]]] = {}
        self._providers: dict[int, object] = {}
        self._active = True

    def close(self) -> None:
        with self._lock:
            self._active = False
            self._entries.clear()
            self._providers.clear()

    def peek(self, owner: str, provider: object, model: str, text: str) -> list[float] | None:
        """Reuse completed query vectors for deferred indexing without waiting."""
        key = (owner, id(provider), model, hashlib.sha256(text.encode()).digest())
        with self._lock:
            future = self._entries.get(key) if self._active else None
        if future is None or not future.done() or future.exception() is not None:
            return None
        vector = future.result()
        return list(vector) if vector and any(vector) else None

    def get(
        self, owner: str, provider: object, model: str, text: str, compute: Callable[[], list[float]]
    ) -> list[float]:
        key = (owner, id(provider), model, hashlib.sha256(text.encode()).digest())
        with self._lock:
            future = self._entries.get(key) if self._active else None
            creator = future is None
            if creator:
                if not self._active or not owner or len(self._entries) >= 64:
                    future = None
                else:
                    future = Future()
                    self._entries[key] = future
                    self._providers[id(provider)] = provider
        if future is None:
            return compute()
        if not creator:
            return list(future.result())
        try:
            vector = list(compute())
            if not vector or not any(vector):
                with self._lock:
                    self._entries.pop(key, None)
            future.set_result(vector)
            return list(vector)
        except BaseException as exc:
            with self._lock:
                self._entries.pop(key, None)
            future.set_exception(exc)
            raise


request_embedding_cache: ContextVar[RequestEmbeddingCache | None] = ContextVar("request_embedding_cache", default=None)
