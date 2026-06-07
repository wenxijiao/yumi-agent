from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from yumi.core.features.config.model import ModelConfig
from yumi.core.features.proactive.interaction import should_give_space, smart_followup_delay_multiplier
from yumi.core.features.proactive.state import ProactiveSessionState, parse_iso
from yumi.core.features.proactive.timezone_utils import (
    in_quiet_hours,
    proactive_calendar_date_iso,
    proactive_tzinfo,
)

# Re-export for callers/tests that imported ``in_quiet_hours`` from this module.
__all__ = (
    "ProactiveDecision",
    "decide_proactive_send",
    "decide_scheduled_proactive_send",
    "decide_smart_proactive_send",
    "in_quiet_hours",
)


@dataclass
class ProactiveDecision:
    should_send: bool
    trigger: str = ""
    reason: str = ""
    scheduled_slot_key: str | None = None
    mark_scheduled_interval: bool = False


def _minutes_since(now: datetime, value: str | None) -> float | None:
    dt = parse_iso(value)
    if dt is None:
        return None
    return max(0.0, (now.astimezone(timezone.utc) - dt).total_seconds() / 60.0)


def _effective_unreplied_escalation_minutes(cfg: ModelConfig, state: ProactiveSessionState) -> float:
    base = float(cfg.proactive_unreplied_escalation_minutes)
    j = float(cfg.proactive_unreplied_escalation_jitter_ratio)
    if j <= 0:
        return base
    digest = hashlib.sha256(f"{state.session_id}\0{state.last_proactive_at or ''}".encode()).digest()
    seed = int.from_bytes(digest[:8], "big")
    rng = random.Random(seed)
    lo = max(0.0, 1.0 - j)
    hi = 1.0 + j
    return base * rng.uniform(lo, hi)


def _proactive_common_guards(cfg: ModelConfig, state: ProactiveSessionState, now: datetime) -> ProactiveDecision | None:
    """Return a blocking decision, or None if checks pass (daily counter may still allow send)."""
    if cfg.proactive_daily_limit <= 0:
        return ProactiveDecision(False, reason="daily_limit_zero")
    if in_quiet_hours(now, cfg.proactive_quiet_hours, cfg.local_timezone):
        return ProactiveDecision(False, reason="quiet_hours")

    today = proactive_calendar_date_iso(now, cfg.local_timezone)
    sent_today = state.sent_today if state.date == today else 0
    if sent_today >= cfg.proactive_daily_limit:
        return ProactiveDecision(False, reason="daily_limit")
    return None


def _scheduled_grace_minutes(cfg: ModelConfig) -> int:
    return max(10, int(cfg.proactive_check_interval_seconds) // 60 + 1)


def _idle_block_if_needed(cfg: ModelConfig, state: ProactiveSessionState, now: datetime) -> ProactiveDecision | None:
    since_user = _minutes_since(now, state.last_user_message_at)
    since_proactive = _minutes_since(now, state.last_proactive_at)
    if since_proactive is not None and since_proactive < cfg.proactive_min_idle_minutes:
        return ProactiveDecision(False, reason="recent_proactive")
    if since_user is not None and since_user < cfg.proactive_min_idle_minutes:
        return ProactiveDecision(False, reason="recent_user_message")
    return None


def decide_scheduled_proactive_send(
    cfg: ModelConfig,
    state: ProactiveSessionState,
    *,
    now: datetime,
) -> ProactiveDecision:
    parsed_times: list[tuple[int, int]] = []
    for t in cfg.proactive_schedule_times or []:
        parts = str(t).strip().split(":")
        if len(parts) == 2:
            try:
                parsed_times.append((int(parts[0]), int(parts[1])))
            except ValueError:
                continue
    interval_min = cfg.proactive_schedule_interval_minutes
    if not parsed_times and interval_min is None:
        return ProactiveDecision(False, reason="scheduled_not_configured")

    blocked = _proactive_common_guards(cfg, state, now)
    if blocked is not None:
        return blocked

    if cfg.proactive_schedule_require_idle:
        idle = _idle_block_if_needed(cfg, state, now)
        if idle is not None:
            return idle

    tz = proactive_tzinfo(cfg.local_timezone)
    local_now = now.astimezone(tz)
    grace = timedelta(minutes=_scheduled_grace_minutes(cfg))

    for h, m in parsed_times:
        slot_local = local_now.replace(hour=h, minute=m, second=0, microsecond=0)
        if slot_local <= local_now < slot_local + grace:
            slot_key = f"{slot_local.date().isoformat()} {h:02d}:{m:02d}"
            if state.last_scheduled_slot == slot_key:
                continue
            return ProactiveDecision(
                True,
                trigger="scheduled_time",
                reason="scheduled_time_window",
                scheduled_slot_key=slot_key,
            )

    if interval_min is not None:
        last_iv = parse_iso(state.last_scheduled_interval_at)
        if last_iv is None:
            return ProactiveDecision(
                True,
                trigger="scheduled_interval",
                reason="scheduled_interval",
                mark_scheduled_interval=True,
            )
        if (now - last_iv).total_seconds() >= float(interval_min) * 60.0:
            return ProactiveDecision(
                True,
                trigger="scheduled_interval",
                reason="scheduled_interval",
                mark_scheduled_interval=True,
            )

    return ProactiveDecision(False, reason="scheduled_no_match")


def decide_smart_proactive_send(
    cfg: ModelConfig,
    state: ProactiveSessionState,
    *,
    now: datetime,
    rng: random.Random,
) -> ProactiveDecision:
    blocked = _proactive_common_guards(cfg, state, now)
    if blocked is not None:
        return blocked

    since_user = _minutes_since(now, state.last_user_message_at)
    since_proactive = _minutes_since(now, state.last_proactive_at)

    if since_proactive is not None and since_proactive < cfg.proactive_min_idle_minutes:
        return ProactiveDecision(False, reason="recent_proactive")
    if since_user is not None and since_user < cfg.proactive_min_idle_minutes:
        return ProactiveDecision(False, reason="recent_user_message")

    if state.unreplied_count > 0:
        if (cfg.proactive_smart_naturalness or "balanced").strip().lower() != "off" and should_give_space(cfg, state):
            return ProactiveDecision(False, reason="give_space_after_unreplied_followups")
        need = _effective_unreplied_escalation_minutes(cfg, state)
        if (cfg.proactive_smart_naturalness or "balanced").strip().lower() != "off":
            need *= smart_followup_delay_multiplier(state)
        if since_proactive is None or since_proactive >= need:
            return ProactiveDecision(True, trigger="unreplied_followup", reason="user_has_not_replied")
        return ProactiveDecision(False, reason="waiting_before_unreplied_followup")

    p = float(cfg.proactive_check_in_probability)
    if rng.random() < p:
        return ProactiveDecision(True, trigger="check_in", reason="random_check_in")
    return ProactiveDecision(False, reason="random_skip")


def decide_proactive_send(
    cfg: ModelConfig,
    state: ProactiveSessionState,
    *,
    now: datetime | None = None,
    rng: random.Random | None = None,
) -> ProactiveDecision:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rng = rng or random.Random()

    mode = (cfg.proactive_mode or "off").strip().lower()
    if mode not in ("off", "smart", "scheduled"):
        mode = "off"

    if mode == "off":
        return ProactiveDecision(False, reason="disabled")

    if mode == "scheduled":
        return decide_scheduled_proactive_send(cfg, state, now=now)

    return decide_smart_proactive_send(cfg, state, now=now, rng=rng)
