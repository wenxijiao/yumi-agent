from yumi.telegram.bot import _format_timer_list_for_telegram


def test_format_timer_list_for_telegram_empty():
    assert _format_timer_list_for_telegram([]) == "No active timers or scheduled tasks."


def test_format_timer_list_for_telegram_contains_cancel_hint():
    text = _format_timer_list_for_telegram(
        [
            {
                "id": "abc123",
                "type": "scheduled",
                "recurring": True,
                "next_fire_at": "2026-05-14T09:00:00",
                "description": "daily check",
            }
        ]
    )

    assert "abc123" in text
    assert "daily check" in text
    assert "/cancel_timer <id>" in text
