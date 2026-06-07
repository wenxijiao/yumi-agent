from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

ACTIVE_TIMERS: dict[str, dict] = {}

try:
    from kumi.core.api.chat_context import get_chat_owner_user_id
except ImportError:

    def get_chat_owner_user_id() -> str:  # pragma: no cover
        return "_local"


def _owner_id() -> str:
    return get_chat_owner_user_id()


_SCHEDULES_PATH = Path.home() / ".kumi" / "schedules.json"

_schedule_callback: Callable | None = None
_cancel_callback: Callable | None = None

_WEEKDAY_NAMES = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}

_CHINESE_WEEKDAY_NAMES = {
    "一": 0,
    "1": 0,
    "二": 1,
    "2": 1,
    "三": 2,
    "3": 2,
    "四": 3,
    "4": 3,
    "五": 4,
    "5": 4,
    "六": 5,
    "6": 5,
    "日": 6,
    "天": 6,
    "7": 6,
}


def set_timer_callbacks(schedule_fn: Callable, cancel_fn: Callable):
    global _schedule_callback, _cancel_callback
    _schedule_callback = schedule_fn
    _cancel_callback = cancel_fn


# ── persistence ──


def _save_schedules():
    items = [v for v in ACTIVE_TIMERS.values() if v.get("type") == "scheduled"]
    try:
        _SCHEDULES_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SCHEDULES_PATH.write_text(
            json.dumps(items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def _load_schedules() -> list[dict]:
    if not _SCHEDULES_PATH.exists():
        return []
    try:
        data = json.loads(_SCHEDULES_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def restore_schedules():
    """Reload persisted schedules and re-register them with the scheduler.

    Called once at server startup from ``api.py`` lifespan.
    """
    items = _load_schedules()
    now = datetime.now()
    changed = False

    for item in items:
        timer_id = item.get("id", "")
        if not timer_id:
            continue

        recurring = item.get("recurring", False)
        next_fire_raw = item.get("next_fire_at", "")
        try:
            next_fire = datetime.fromisoformat(next_fire_raw)
        except (ValueError, TypeError):
            changed = True
            continue

        if next_fire <= now:
            if recurring:
                next_fire = _advance_recurring(item, now)
                item["next_fire_at"] = next_fire.isoformat()
                changed = True
            else:
                changed = True
                continue

        delay = max(1, int((next_fire - now).total_seconds()))
        if "owner_user_id" not in item:
            item = {**item, "owner_user_id": "_local"}
        ACTIVE_TIMERS[timer_id] = item

        if _schedule_callback:
            _schedule_callback(
                timer_id,
                delay,
                item.get("description", ""),
                item.get("session_id", "default"),
            )

    if changed:
        _save_schedules()


# ── when parser ──


def _parse_time(time_str: str) -> tuple[int, int]:
    parts = time_str.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time: {time_str}")
    h, m = int(parts[0]), int(parts[1])
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"Time out of range: {time_str}")
    return h, m


def _parse_weekday_tokens(day_part: str) -> list[int]:
    weekdays: list[int] = []
    for token in re.split(r"[,\s，、]+", day_part):
        token = token.strip()
        if not token:
            continue
        normalized = token
        for prefix in ("每星期", "星期", "礼拜", "每礼拜", "每周", "周"):
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :]
                break
        if normalized in _CHINESE_WEEKDAY_NAMES:
            weekdays.append(_CHINESE_WEEKDAY_NAMES[normalized])
        elif token in _WEEKDAY_NAMES:
            weekdays.append(_WEEKDAY_NAMES[token])
        else:
            raise ValueError(
                f"Unknown weekday '{token}'. Use english weekday names (e.g. monday, tue, fri) "
                "or Chinese weekdays (e.g. 周一, 周三, 周五)."
            )
    if not weekdays:
        raise ValueError("No weekdays specified.")
    return sorted(set(weekdays))


def _next_weekday(target_weekday: int, hour: int, minute: int) -> datetime:
    now = datetime.now()
    days_ahead = (target_weekday - now.weekday()) % 7
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0) + timedelta(days=days_ahead)
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


def _parse_when(when: str) -> dict:
    """Parse a ``when`` string into a scheduling descriptor.

    Returns a dict with keys:
        next_fire_at  (datetime)
        recurring     (bool)
        weekdays      (list[int] | None)   – for recurring
        time          (str "HH:MM" | None)  – for recurring
        when_raw      (str)                 – original input
    """
    raw = when.strip()
    text = raw.lower()

    # ── recurring daily: "daily 07:00" / "every day 07:00" / "每天07:00" ──
    m = re.match(r"(?:daily|everyday|every\s+day)\s+(\d{1,2}:\d{2})$|(?:每天|每日)\s*(\d{1,2}:\d{2})$", text)
    if m:
        time_part = m.group(1) or m.group(2)
        hour, minute = _parse_time(time_part)
        weekdays = list(range(7))
        nearest = min(
            (_next_weekday(wd, hour, minute) for wd in weekdays),
            key=lambda dt: dt,
        )
        return {
            "next_fire_at": nearest,
            "recurring": True,
            "weekdays": weekdays,
            "time": time_part,
            "when_raw": raw,
        }

    # ── recurring weekly in Chinese: "每周一07:00" / "每周一,三,五 09:30" ──
    m = re.match(r"(?:每周|每星期|每礼拜)\s*(.+?)\s*(\d{1,2}:\d{2})$", text)
    if m:
        day_part, time_part = m.group(1), m.group(2)
        hour, minute = _parse_time(time_part)
        weekdays = _parse_weekday_tokens(day_part)

        nearest = min(
            (_next_weekday(wd, hour, minute) for wd in weekdays),
            key=lambda dt: dt,
        )
        return {
            "next_fire_at": nearest,
            "recurring": True,
            "weekdays": weekdays,
            "time": time_part,
            "when_raw": raw,
        }

    # ── recurring weekly: "every monday 07:00" / "every mon,thu 09:30" ──
    m = re.match(r"every\s+(.+?)\s+(\d{1,2}:\d{2})$", text)
    if m:
        day_part, time_part = m.group(1), m.group(2)
        hour, minute = _parse_time(time_part)
        weekdays = _parse_weekday_tokens(day_part)

        nearest = min(
            (_next_weekday(wd, hour, minute) for wd in weekdays),
            key=lambda dt: dt,
        )
        return {
            "next_fire_at": nearest,
            "recurring": True,
            "weekdays": sorted(set(weekdays)),
            "time": time_part,
            "when_raw": raw,
        }

    # ── single weekday: "friday 17:00" ──
    m = re.match(r"(\w+)\s+(\d{1,2}:\d{2})$", text)
    if m and m.group(1) in _WEEKDAY_NAMES:
        day_name, time_part = m.group(1), m.group(2)
        hour, minute = _parse_time(time_part)
        target = _next_weekday(_WEEKDAY_NAMES[day_name], hour, minute)
        return {
            "next_fire_at": target,
            "recurring": False,
            "weekdays": None,
            "time": None,
            "when_raw": raw,
        }

    # ── absolute datetime: "2026-04-23 17:00" ──
    m = re.match(r"(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})$", text)
    if m:
        target = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%Y-%m-%d %H:%M")
        if target <= datetime.now():
            raise ValueError(f"The specified time {raw} is in the past.")
        return {
            "next_fire_at": target,
            "recurring": False,
            "weekdays": None,
            "time": None,
            "when_raw": raw,
        }

    # ── simple time: "23:10" ──
    m = re.match(r"(\d{1,2}:\d{2})$", text)
    if m:
        hour, minute = _parse_time(m.group(1))
        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return {
            "next_fire_at": target,
            "recurring": False,
            "weekdays": None,
            "time": None,
            "when_raw": raw,
        }

    raise ValueError(
        f"Cannot parse '{raw}'. Supported formats: "
        "'HH:MM', 'YYYY-MM-DD HH:MM', 'friday 17:00', "
        "'daily 07:00', 'every day 07:00', '每天 07:00', "
        "'every monday 07:00', 'every tue,thu 09:30', '每周一,三,五 09:30'."
    )


def _advance_recurring(item: dict, after: datetime) -> datetime:
    """Compute the next fire time for a recurring schedule after *after*."""
    weekdays = item.get("weekdays", [])
    time_str = item.get("time", "07:00")
    hour, minute = _parse_time(time_str)

    candidates = [_next_weekday(wd, hour, minute) for wd in weekdays]
    candidates = [c if c > after else c + timedelta(days=7) for c in candidates]
    return min(candidates)


def calc_next_recurring_delay(item: dict) -> int:
    """Return seconds until the next occurrence of a recurring schedule."""
    now = datetime.now()
    next_fire = _advance_recurring(item, now)
    item["next_fire_at"] = next_fire.isoformat()
    return max(1, int((next_fire - now).total_seconds()))


def timer_entries_for_owner(owner_user_id: str | None = None) -> list[dict]:
    oid = owner_user_id or _owner_id()
    visible = list(ACTIVE_TIMERS.values())
    if oid != "_local":
        visible = [t for t in visible if t.get("owner_user_id", oid) == oid]
    return visible


def cancel_timer_for_owner(timer_id: str, owner_user_id: str | None = None) -> tuple[bool, str, dict | None]:
    if timer_id not in ACTIVE_TIMERS:
        return False, f"Error: no active timer or task with ID '{timer_id}'.", None

    oid = owner_user_id or _owner_id()
    info = ACTIVE_TIMERS[timer_id]
    if oid != "_local" and info.get("owner_user_id") and info.get("owner_user_id") != oid:
        return False, f"Error: timer '{timer_id}' belongs to another user.", None

    info = ACTIVE_TIMERS.pop(timer_id)

    if info.get("type") == "scheduled":
        _save_schedules()

    if _cancel_callback:
        _cancel_callback(timer_id)

    return True, f"Cancelled '{timer_id}'. (Was: {info['description']})", info


# ── tools ──


def set_timer(delay_seconds: int, description: str, session_id: str = "default") -> str:
    if delay_seconds <= 0:
        return "Error: delay_seconds must be a positive integer."
    if not description.strip():
        return "Error: description cannot be empty."

    timer_id = uuid.uuid4().hex[:8]
    fire_at = datetime.now() + timedelta(seconds=delay_seconds)

    ACTIVE_TIMERS[timer_id] = {
        "id": timer_id,
        "type": "timer",
        "description": description,
        "fire_at": fire_at.isoformat(),
        "session_id": session_id,
        "owner_user_id": _owner_id(),
        "created_at": datetime.now().isoformat(),
    }

    if _schedule_callback:
        _schedule_callback(timer_id, delay_seconds, description, session_id)

    return (
        f"Timer '{timer_id}' set. It will fire in {delay_seconds} seconds "
        f"(at {fire_at.strftime('%H:%M:%S')}). Description: {description}"
    )


def schedule_task(when: str, description: str, session_id: str = "default") -> str:
    if not description.strip():
        return "Error: description cannot be empty."

    try:
        parsed = _parse_when(when)
    except ValueError as exc:
        return f"Error: {exc}"

    timer_id = uuid.uuid4().hex[:8]
    next_fire: datetime = parsed["next_fire_at"]
    delay_seconds = max(1, int((next_fire - datetime.now()).total_seconds()))
    recurring = parsed["recurring"]

    entry = {
        "id": timer_id,
        "type": "scheduled",
        "description": description,
        "when_raw": parsed["when_raw"],
        "recurring": recurring,
        "weekdays": parsed["weekdays"],
        "time": parsed["time"],
        "next_fire_at": next_fire.isoformat(),
        "fire_at": next_fire.isoformat(),
        "session_id": session_id,
        "owner_user_id": _owner_id(),
        "created_at": datetime.now().isoformat(),
    }
    ACTIVE_TIMERS[timer_id] = entry
    _save_schedules()

    if _schedule_callback:
        _schedule_callback(timer_id, delay_seconds, description, session_id)

    label = "Recurring task" if recurring else "Task"
    schedule_desc = parsed["when_raw"]
    return (
        f"{label} '{timer_id}' scheduled ({schedule_desc}). "
        f"Next: {next_fire.strftime('%Y-%m-%d %H:%M')}. "
        f"Description: {description}"
    )


def list_timers() -> str:
    visible = timer_entries_for_owner()

    if not visible:
        return "No active timers or scheduled tasks."

    lines = [f"Active items ({len(visible)}):"]
    for t in visible:
        fire_at = t.get("next_fire_at") or t.get("fire_at", "")
        try:
            dt = datetime.fromisoformat(fire_at)
            fire_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            fire_str = fire_at
        kind = t.get("type", "timer")
        recurring_tag = " [recurring]" if t.get("recurring") else ""
        lines.append(f"  [{t['id']}] ({kind}{recurring_tag}) next: {fire_str} — {t['description']}")
    return "\n".join(lines)


def cancel_timer(timer_id: str) -> str:
    _ok, message, _info = cancel_timer_for_owner(timer_id)
    return message
