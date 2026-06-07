"""Structured HTTP error bodies for the Kumi API (FastAPI ``HTTPException`` ``detail`` dicts)."""

from __future__ import annotations

from fastapi import HTTPException
from kumi.core.platform.exceptions import ProviderNotReadyError
from kumi.logging_config import get_logger

_log = get_logger(__name__)


def provider_not_ready_http(exc: ProviderNotReadyError) -> HTTPException:
    """Map :class:`ProviderNotReadyError` to an HTTP response with a stable ``code`` field."""
    status = 503 if exc.code == "KUMI_OLLAMA_UNAVAILABLE" else 400
    return HTTPException(
        status_code=status,
        detail={
            "code": exc.code,
            "message": str(exc),
            "hint": exc.hint,
        },
    )


def unknown_provider_http(*, role: str, name: str, supported: tuple[str, ...]) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={
            "code": "KUMI_UNKNOWN_PROVIDER",
            "message": f"Unknown {role} provider: {name!r}.",
            "hint": f"Supported: {', '.join(supported)}",
        },
    )


def model_apply_failed_http(*, phase: str, exc: Exception) -> HTTPException:
    """Provider init or model switch failed after config was saved.

    The full provider exception (which can embed URLs, request IDs, or partial
    credential fragments from the SDK) is logged server-side; the HTTP response
    only carries a generic hint pointing the operator at the logs.
    """
    _log.exception("Provider model apply failed during %s phase", phase)
    return HTTPException(
        status_code=502,
        detail={
            "code": "KUMI_PROVIDER_MODEL_APPLY_FAILED",
            "message": f"Could not apply model configuration ({phase}).",
            "hint": "Check provider credentials and base_url; see server logs for the full error.",
        },
    )
