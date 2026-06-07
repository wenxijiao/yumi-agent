"""Yumi SDK integration for the Planner (schedule) demo."""

from __future__ import annotations

from yumi.demo.planner.app import (
    add_event,
    clear_schedule,
    get_schedule,
    remove_event,
    set_reminder,
    update_event,
)
from yumi.sdk import YumiAgent


def init_yumi(connection_code: str | None = None) -> YumiAgent:
    agent = YumiAgent(connection_code=connection_code, edge_name="Planner-Demo")

    agent.register(
        add_event,
        "Add a calendar event: title, date (today/tomorrow/YYYY-MM-DD), time (HH:MM), duration_minutes (15-480), "
        "category (work, personal, health, meeting, other)",
    )
    agent.register(remove_event, "Remove the first event whose title matches (case-insensitive)")
    agent.register(
        update_event,
        "Update an event matched by title; pass new_title/new_date/new_time/new_duration_minutes/new_category "
        "as empty string or -1 for duration to leave unchanged",
    )
    agent.register(
        get_schedule,
        "Focus the planner UI on a date (today/tomorrow/YYYY-MM-DD) and return that day's events as text",
    )
    agent.register(
        clear_schedule,
        "Clear events: pass date (today/tomorrow/YYYY-MM-DD) to clear that day only, or empty/all to clear everything",
    )
    agent.register(
        set_reminder,
        "Set minutes_before reminder on the first event matching title (shows bell on the timeline)",
    )

    agent.run_in_background()
    return agent
