"""Server-side tool registration — mirrors the edge ``init_yumi`` pattern.

Built-in tools are plain functions registered explicitly via
:func:`~yumi.core.platform.tools.tool.register_tool`.
"""

from __future__ import annotations

from yumi.core.features.proactive.timer_tools import cancel_timer, list_timers, schedule_task, set_timer
from yumi.core.platform.tools.tool import register_tool
from yumi.tools.file_tools import list_files, read_file
from yumi.tools.user_context_tools import forget_user_context, list_user_context, remember_user_context
from yumi.tools.web_tools import fetch_webpage, get_weather, web_search


def init_yumi() -> None:
    """Register all built-in server tools."""

    # ── timer tools ──

    register_tool(
        set_timer,
        (
            "Schedule a one-shot ACTION after a short relative delay (seconds / minutes). "
            "When the timer fires the system runs another model turn with your description so "
            "you can call another tool or send a chat reply. "
            "USE WHEN the user's intent is 'do X after N seconds/minutes' — e.g. "
            "'play music in 5 minutes', 'turn off the lights in 30 seconds', "
            "'1 分钟后跟我说我爱你'. "
            "DO NOT USE for user-visible reminders / calendar items / tasks that should persist "
            "and show up in a list — if the deployment has a calendar-style tool (e.g. "
            "``create_event``, ``add_task``, ``create_reminder``), route those there instead so "
            "the user can see, edit and find them later. "
            "Timer state lives in process memory and is invisible to the user."
        ),
        params={
            "delay_seconds": "Seconds until the timer fires (e.g. 60 for one minute)",
            "description": (
                "Exact action to perform when the timer fires—include tool names if needed "
                "(weather lookup, search, short reply, etc.)"
            ),
            "session_id": "Leave default so the same chat session receives the follow-up",
        },
        returns="Confirmation with timer ID",
    )

    register_tool(
        schedule_task,
        (
            "Schedule a one-shot or recurring ACTION at a specific clock time / date / weekday. "
            "Same pattern as set_timer but expressed in wall-clock terms. When the schedule "
            "fires, the system runs a new model turn with your description so you can call "
            "another tool or message the user. "
            "USE WHEN the user wants an automated action — e.g. 'turn off the lights at 10pm', "
            "'every weekday 9am post the standup question'. "
            "DO NOT USE for personal reminders / tasks / habits the user expects to see and "
            "manage in their app. If the deployment exposes a calendar-style tool (e.g. "
            "``create_event``, ``add_task``, ``create_reminder``), prefer that — those items "
            "are persisted, editable, surfaced in a UI, and survive a server restart. "
            "schedule_task lives only in process memory."
        ),
        params={
            "when": (
                "When to fire. Supported formats: "
                "'23:10' (today or tomorrow), "
                "'2026-04-23 17:00' (specific date), "
                "'friday 17:00' (next Friday), "
                "'daily 07:00', 'every day 07:00', or '每天 07:00' (recurring daily), "
                "'every tuesday 07:00' (recurring weekly), "
                "'every mon,thu 09:30' or '每周一,三,五 09:30' (recurring multiple days)"
            ),
            "description": "What to do when the scheduled time arrives",
            "session_id": "Chat session that should receive the notification (default: current session)",
        },
        returns="Confirmation with task ID and scheduled time",
    )

    register_tool(
        list_timers,
        "List all active timers and scheduled tasks.",
        returns="A formatted list of active timers and tasks, or a message saying none are active",
    )

    register_tool(
        cancel_timer,
        "Cancel an active timer or scheduled task by its ID.",
        params={
            "timer_id": "The ID of the timer/task to cancel (from set_timer / schedule_task / list_timers)",
        },
        returns="Confirmation that the item was cancelled, or an error if not found",
    )

    # ── file tools ──

    register_tool(
        read_file,
        (
            "Read a local file on the Yumi server and return its text (or extracted text for PDF/DOCX). "
            "Whenever the user message contains an absolute path—especially under `.yumi/uploads/`—"
            "you MUST call this tool with that exact path before answering; do not claim you cannot read files. "
            "Supports plain text, PDF, Word (.docx), CSV, JSON, and common code/markup types."
        ),
        params={
            "file_path": (
                "Absolute or relative path to the file. "
                "Supports ~ for home directory. "
                "Example: '/Users/me/report.pdf' or '~/Documents/notes.txt'"
            ),
        },
        returns="The text content extracted from the file",
        default_require_confirmation=True,
    )

    register_tool(
        list_files,
        "List files in a directory. Use this to help the user find files before reading them.",
        params={
            "directory_path": (
                "Absolute or relative path to the directory. "
                "Supports ~ for home directory. "
                "Example: '/Users/me/Documents' or '~/Downloads'"
            ),
            "pattern": (
                "Optional glob pattern to filter files. "
                "Example: '*.pdf' to list only PDFs, '*.txt' for text files. "
                "Default: '*' (all files)"
            ),
        },
        returns="A list of files in the directory with sizes",
        default_require_confirmation=True,
    )

    # ── web tools ──

    register_tool(
        web_search,
        (
            "Search the live web (news, current events, prices, docs, anything). "
            "Uses the configured search provider (Tavily / Brave / Serper / SearXNG) and "
            "falls back to DuckDuckGo automatically. For time-sensitive questions — recent "
            "news, 'latest X', today's events — pass time_range='day' or 'week'. "
            "Results are snippets; call fetch_webpage on a result URL to read the full page."
        ),
        params={
            "query": "The search keywords or question to look up (any language)",
            "max_results": "Maximum number of results to return, between 1 and 10",
            "time_range": (
                "Optional recency filter: 'day', 'week', 'month', or 'year'. "
                "Use 'day'/'week' for news and current events. Empty = no filter."
            ),
        },
        returns="Numbered list of live search results with titles, snippets, URLs, and dates when available",
    )

    register_tool(
        fetch_webpage,
        (
            "Fetch a web page by URL and return its readable text content. "
            "Only public http(s) URLs are allowed; local, private-network, and cloud metadata URLs are blocked. "
            "Use this after web_search to read the full article behind a promising result, "
            "or whenever the user shares a link."
        ),
        params={
            "url": "The public http(s) URL to fetch",
            "max_chars": "Maximum characters of page text to return (500–30000, default 6000)",
        },
        returns="The page title and extracted text, truncated to max_chars",
    )

    register_tool(
        get_weather,
        "Get the current weather for a city or location.",
        params={
            "location": "City name or geographic location to get weather for",
        },
        returns="Current weather conditions including temperature, humidity, and wind speed",
    )

    # Durable user context tools

    register_tool(
        remember_user_context,
        (
            "Save a durable Stable User Context memory. Use this only when the user explicitly asks "
            "Yumi to remember something, or when they confirm a suggested memory should be saved. "
            "Do not use it for ordinary transient chat details."
        ),
        params={
            "content": "The concise durable memory to save.",
            "kind": (
                "Memory category, such as profile, preference, routine, project, relationship, "
                "constraint, communication_style, do_not_assume, fact, decision, task_state, or summary."
            ),
            "importance": "0.0 to 1.0 importance score. Use 0.85 for normal explicit user memories.",
        },
        returns="The saved memory id and content.",
    )

    register_tool(
        list_user_context,
        "List saved Stable User Context memories, including ids that can be used to forget one.",
        params={
            "kind": "Optional memory category filter. Leave empty to list all stable context memories.",
            "limit": "Maximum number of memories to return, between 1 and 50.",
        },
        returns="Saved stable user context memories with ids.",
    )

    register_tool(
        forget_user_context,
        "Delete a saved Stable User Context memory by id after the user asks Yumi to forget it.",
        params={
            "memory_id": "The memory id returned by list_user_context or remember_user_context.",
        },
        returns="Confirmation that the memory was forgotten, or a not-found message.",
    )
