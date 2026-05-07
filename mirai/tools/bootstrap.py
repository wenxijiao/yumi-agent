"""Server-side tool registration — mirrors the edge ``init_mirai`` pattern.

Built-in tools are plain functions registered explicitly via
:func:`~mirai.core.tool.register_tool`.
"""

from __future__ import annotations

from mirai.core.tool import register_tool
from mirai.tools.file_tools import list_files, read_file
from mirai.tools.timer_tools import cancel_timer, list_timers, schedule_task, set_timer
from mirai.tools.web_tools import get_weather, web_search


def init_mirai() -> None:
    """Register all built-in server tools."""

    # ── timer tools ──

    register_tool(
        set_timer,
        (
            "REQUIRED for relative delays: when the user says 'after N seconds/minutes', "
            "'in one minute', 'remind me later', etc. Call this tool—do not only promise in chat text. "
            "After delay_seconds, the system runs another model turn with your description so you can "
            "call get_weather, web_search, or reply to the user. "
            "Put the full intended action in description (e.g. 'call get_weather for Shanghai and summarize')."
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
            "Schedule a task at a specific date/time, or on a recurring basis. "
            "Use this when the user specifies a clock time, a date, a weekday, or a repeating schedule. "
            "Use set_timer instead only when the user says 'after N minutes/seconds'."
        ),
        params={
            "when": (
                "When to fire. Supported formats: "
                "'23:10' (today or tomorrow), "
                "'2026-04-23 17:00' (specific date), "
                "'friday 17:00' (next Friday), "
                "'every tuesday 07:00' (recurring weekly), "
                "'every mon,thu 09:30' (recurring multiple days)"
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
            "Read a local file on the Mirai server and return its text (or extracted text for PDF/DOCX). "
            "Whenever the user message contains an absolute path—especially under `.mirai/uploads/`—"
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
        "Search the web for recent information and return a concise summary.",
        params={
            "query": "The search keywords or question to look up",
            "max_results": "Maximum number of results to return, between 1 and 10",
        },
        returns="Numbered list of search results with titles, descriptions, and URLs",
    )

    register_tool(
        get_weather,
        "Get the current weather for a city or location.",
        params={
            "location": "City name or geographic location to get weather for",
        },
        returns="Current weather conditions including temperature, humidity, and wind speed",
    )
