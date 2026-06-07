from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kumi.core.config.paths import CONFIG_DIR, ensure_config_dir
from kumi.core.config.store import load_model_config
from kumi.core.proactive.timezone_utils import proactive_calendar_date_iso
from kumi.logging_config import get_logger

logger = get_logger(__name__)

STATE_PATH = CONFIG_DIR / "proactive_state.json"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass
class ProactiveSessionState:
    session_id: str
    date: str = ""
    sent_today: int = 0
    last_proactive_at: str | None = None
    last_user_message_at: str | None = None
    last_trigger: str | None = None
    unreplied_count: int = 0
    last_scheduled_slot: str | None = None
    last_scheduled_interval_at: str | None = None


class ProactiveStateStore:
    def __init__(self, path: Path | None = None):
        self.path = path or STATE_PATH

    def _load_raw(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"sessions": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"sessions": {}}
        if not isinstance(data, dict):
            return {"sessions": {}}
        sessions = data.get("sessions")
        if not isinstance(sessions, dict):
            data["sessions"] = {}
        return data

    def _save_raw(self, data: dict[str, Any]) -> None:
        try:
            ensure_config_dir()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.debug("Could not save proactive state: %s", exc)

    def get(self, session_id: str) -> ProactiveSessionState:
        raw = self._load_raw().get("sessions", {}).get(session_id, {})
        if not isinstance(raw, dict):
            raw = {}
        return ProactiveSessionState(
            session_id=session_id,
            date=str(raw.get("date") or ""),
            sent_today=int(raw.get("sent_today") or 0),
            last_proactive_at=raw.get("last_proactive_at") or None,
            last_user_message_at=raw.get("last_user_message_at") or None,
            last_trigger=raw.get("last_trigger") or None,
            unreplied_count=int(raw.get("unreplied_count") or 0),
            last_scheduled_slot=raw.get("last_scheduled_slot") or None,
            last_scheduled_interval_at=raw.get("last_scheduled_interval_at") or None,
        )

    def put(self, state: ProactiveSessionState) -> None:
        data = self._load_raw()
        sessions = data.setdefault("sessions", {})
        sessions[state.session_id] = asdict(state)
        self._save_raw(data)

    def record_user_message(self, session_id: str, *, at: datetime | None = None) -> None:
        state = self.get(session_id)
        state.last_user_message_at = (at or utc_now()).astimezone(timezone.utc).isoformat()
        state.unreplied_count = 0
        self.put(state)

    def record_sent(
        self,
        session_id: str,
        *,
        trigger: str,
        at: datetime | None = None,
        scheduled_slot_key: str | None = None,
        mark_scheduled_interval: bool = False,
    ) -> None:
        now = (at or utc_now()).astimezone(timezone.utc)
        cfg = load_model_config()
        today = proactive_calendar_date_iso(now, cfg.local_timezone)
        state = self.get(session_id)
        if state.date != today:
            state.date = today
            state.sent_today = 0
        state.sent_today += 1
        state.last_proactive_at = now.isoformat()
        state.last_trigger = trigger
        state.unreplied_count += 1
        if scheduled_slot_key:
            state.last_scheduled_slot = scheduled_slot_key
        if mark_scheduled_interval:
            state.last_scheduled_interval_at = now.isoformat()
        self.put(state)


def record_user_message(session_id: str) -> None:
    """Best-effort hook for chat bridges to mark that the user replied."""
    try:
        ProactiveStateStore().record_user_message(session_id)
    except Exception as exc:
        logger.debug("Proactive user-message hook skipped: %s", exc)
