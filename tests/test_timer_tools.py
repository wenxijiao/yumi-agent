import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from yumi.core.features.proactive import timer_tools
from yumi.core.features.proactive.timer_tools import SchedulerService, _parse_when
from yumi.core.platform.tools.tool import TOOL_REGISTRY, execute_registered_tool


def test_parse_daily_recurring_schedule():
    parsed = _parse_when("daily 09:00")

    assert parsed["recurring"] is True
    assert parsed["weekdays"] == [0, 1, 2, 3, 4, 5, 6]
    assert parsed["time"] == "09:00"
    assert parsed["when_raw"] == "daily 09:00"


def test_parse_every_day_recurring_schedule():
    parsed = _parse_when("every day 18:30")

    assert parsed["recurring"] is True
    assert parsed["weekdays"] == [0, 1, 2, 3, 4, 5, 6]
    assert parsed["time"] == "18:30"
    assert parsed["when_raw"] == "every day 18:30"


def test_parse_chinese_daily_recurring_schedule():
    parsed = _parse_when("每天08:15")

    assert parsed["recurring"] is True
    assert parsed["weekdays"] == [0, 1, 2, 3, 4, 5, 6]
    assert parsed["time"] == "08:15"
    assert parsed["when_raw"] == "每天08:15"


def test_parse_chinese_weekly_recurring_schedule():
    parsed = _parse_when("每周一,三,五18:30")

    assert parsed["recurring"] is True
    assert parsed["weekdays"] == [0, 2, 4]
    assert parsed["time"] == "18:30"
    assert parsed["when_raw"] == "每周一,三,五18:30"


def test_clock_schedule_uses_configured_timezone():
    target = _parse_when("20:08", "Pacific/Auckland")["next_fire_at"]
    assert target.tzinfo is not None
    assert target.hour == 20
    assert target.minute == 8
    assert target.utcoffset() in {timedelta(hours=12), timedelta(hours=13)}


def test_registered_timer_tool_starts_on_event_loop_and_survives_restart(tmp_path, monkeypatch):
    service = SchedulerService(schedules_path=tmp_path / "schedules.json")
    scheduled = asyncio.Event()

    def callback(timer_id, delay, description, session_id):
        asyncio.get_running_loop()
        scheduled.set()

    service.set_callbacks(callback, lambda _: None)
    monkeypatch.setattr(timer_tools, "scheduler", service)
    monkeypatch.setitem(TOOL_REGISTRY, "set_timer", {"callable": timer_tools.set_timer})

    async def invoke():
        result = await execute_registered_tool("set_timer", {
            "delay_seconds": 1200,
            "description": "Turn on the room lights",
            "session_id": "personal-test",
        })
        await asyncio.wait_for(scheduled.wait(), timeout=1)
        assert "Timer '" in result
        assert "in 1200 seconds" in result
        assert "(at " not in result

    asyncio.run(invoke())
    restored = SchedulerService(schedules_path=tmp_path / "schedules.json")
    restored.set_callbacks(lambda *_: None, lambda _: None)
    restored.restore_schedules()
    assert len(restored.active_timers) == 1
    assert next(iter(restored.active_timers.values()))["type"] == "timer"


def test_stale_one_shot_does_not_turn_on_lights_after_long_outage(tmp_path):
    service = SchedulerService(schedules_path=tmp_path / "schedules.json")
    fire_at = datetime.now(timezone.utc) - timedelta(hours=1)
    service.active_timers["old"] = {
        "id": "old", "type": "timer", "description": "Turn on lights",
        "fire_at": fire_at.isoformat(), "session_id": "personal-test",
    }
    service._save_schedules()
    restored = SchedulerService(schedules_path=tmp_path / "schedules.json")
    restored.set_callbacks(lambda *_: pytest.fail("stale light command fired"), lambda _: None)
    restored.restore_schedules()
    assert not restored.active_timers
    assert not restored._load_schedules()
