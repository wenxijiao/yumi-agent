"""Domain exceptions shared across Kumi core (no HTTP dependencies)."""


class ProviderNotReadyError(RuntimeError):
    """Raised when a provider cannot be used (missing credentials, Ollama down, etc.)."""

    def __init__(self, code: str, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.hint = hint
