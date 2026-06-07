"""Domain exceptions shared across Yumi core (no HTTP dependencies).

A small hierarchy so call sites can catch *intent* rather than bare
``Exception``. ``YumiError`` is the common root; narrow subclasses let callers
distinguish provider, tool, edge, memory and config failures. Legitimate
best-effort boundaries (top-level task loops) may still log-and-swallow broadly
— those are marked with ``# noqa: BLE001`` so the intent is explicit and the
``BLE001`` lint can guard against accidental broad catches elsewhere.
"""


class YumiError(Exception):
    """Root of all Yumi domain errors."""


class ProviderError(YumiError):
    """A chat/embedding provider failed (request shaping, transport, decode)."""


class ProviderNotReadyError(ProviderError, RuntimeError):
    """Raised when a provider cannot be used (missing credentials, Ollama down, etc.).

    Also a ``RuntimeError`` subclass for backward compatibility with callers
    that catch ``RuntimeError``.
    """

    def __init__(self, code: str, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.hint = hint


class ToolExecutionError(YumiError):
    """A tool failed to execute (local Python tool or its arguments)."""


class EdgeProtocolError(YumiError):
    """An edge-device RPC / WebSocket exchange failed or timed out."""


class MemoryStoreError(YumiError):
    """The memory backend (LanceDB / embeddings) failed."""


class ConfigError(YumiError):
    """Configuration could not be loaded, validated or persisted."""
