"""Light-weight audit event logger (delegates to the registered :class:`AuditSink`)."""

from __future__ import annotations

from yumi.core.platform.plugins import get_audit_sink


def audit_event(event: str, user_id: str | None = None, **fields: object) -> None:
    """Emit an audit event through the active sink.

    The default sink writes to the standard logger only. Plugins can swap in a
    sink that also persists rows to SQLite/Postgres.
    """
    get_audit_sink().event(event, user_id, **fields)
