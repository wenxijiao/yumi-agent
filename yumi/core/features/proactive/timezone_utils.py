"""IANA timezone helpers for proactive quiet hours and daily limit rollover."""

from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from yumi.logging_config import get_logger

logger = get_logger(__name__)


def proactive_tzinfo(tz_name: str | None):
    """Return ZoneInfo for IANA name, or UTC when unset/invalid."""
    if not tz_name or not str(tz_name).strip():
        return timezone.utc
    try:
        return ZoneInfo(str(tz_name).strip())
    except Exception:
        logger.warning("Invalid local_timezone %r; using UTC.", tz_name)
        return timezone.utc


def proactive_calendar_date_iso(now_utc: datetime, tz_name: str | None) -> str:
    """Calendar date (YYYY-MM-DD) for daily proactive counters in the configured timezone."""
    return now_utc.astimezone(proactive_tzinfo(tz_name)).date().isoformat()


def format_user_facing_time(now_utc: datetime, configured_iana_tz: str | None) -> str:
    """Wall-clock string for prompts (chat [Current Time], proactive context).

    When ``configured_iana_tz`` is set (e.g. ``Pacific/Auckland``), use that zone.
    When unset, use the **host** system local zone (``now_utc.astimezone()`` without args),
    matching typical ``datetime.now()`` behaviour on a correctly configured desktop.
    """
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    else:
        now_utc = now_utc.astimezone(timezone.utc)
    label = (configured_iana_tz or "").strip()
    if label:
        local = now_utc.astimezone(proactive_tzinfo(label))
    else:
        local = now_utc.astimezone()
    return local.strftime("%Y-%m-%d %H:%M:%S %A")


def _parse_clock(value: str) -> time | None:
    try:
        hour_s, minute_s = value.strip().split(":", 1)
        hour = int(hour_s)
        minute = int(minute_s)
    except (ValueError, TypeError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return time(hour=hour, minute=minute)


def in_quiet_hours(now_utc: datetime, quiet_hours: str, tz_name: str | None = None) -> bool:
    """True when local wall time (in configured tz, default UTC) falls inside quiet_hours."""
    if not quiet_hours or "-" not in quiet_hours:
        return False
    start_s, end_s = quiet_hours.split("-", 1)
    start = _parse_clock(start_s)
    end = _parse_clock(end_s)
    if start is None or end is None:
        return False
    local = now_utc.astimezone(proactive_tzinfo(tz_name))
    current = local.time().replace(second=0, microsecond=0)
    if start <= end:
        return start <= current < end
    return current >= start or current < end
