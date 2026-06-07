"""Domain exceptions shared across Kumi core (no HTTP dependencies).

A small hierarchy so call sites can catch *intent* rather than bare
``Exception``. ``KumiError`` is the common root; narrow subclasses let callers
distinguish provider, tool, edge, memory and config failures. Legitimate
best-effort boundaries (top-level task loops) may still log-and-swallow broadly
— those are marked with ``# noqa: BLE001`` so the intent is explicit and the
``BLE001`` lint can guard against accidental broad catches elsewhere.
"""


class KumiError(Exception):
    """Root of all Kumi domain errors."""


class ProviderError(KumiError):
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


class ToolExecutionError(KumiError):
    """A tool failed to execute (local Python tool or its arguments)."""


class EdgeProtocolError(KumiError):
    """An edge-device RPC / WebSocket exchange failed or timed out."""


class MemoryStoreError(KumiError):
    """The memory backend (LanceDB / embeddings) failed."""


class ConfigError(KumiError):
    """Configuration could not be loaded, validated or persisted."""
