from kumi.tools.timer_tools import _parse_when


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
