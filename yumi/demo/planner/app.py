"""Yumi Planner — schedule / memo demo for ``yumi --demo``.

Tkinter day timeline + mini calendar. Tools mirror a real CRUD-style app so the
LLM can demonstrate controlling *software* while Smart Home shows *hardware*.

Process wiring: call ``init_yumi()`` from ``__main__.py`` (after ``Tk()``), then
construct ``PlannerGUI(root, agent)`` — same idea as ``yumi_tools`` / other languages.
"""

from __future__ import annotations

import calendar
import threading
import time
from datetime import date, datetime, timedelta
from typing import Any

_lock = threading.RLock()

CATEGORIES = ("work", "personal", "health", "meeting", "other")
CAT_COLORS = {
    "work": "#bae6fd",
    "personal": "#bbf7d0",
    "health": "#fde68a",
    "meeting": "#ddd6fe",
    "other": "#fbcfe8",
}

PLANNER: dict[str, Any] = {
    "view_year": 0,
    "view_month": 0,
    "selected": "",  # YYYY-MM-DD
    "events": [],
    "next_id": 1,
    "last_query": "",
}

EVENT_LOG: list[str] = []
MAX_LOG = 6

HOUR_START = 6
HOUR_END = 23
HOUR_PX = 34


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    with _lock:
        EVENT_LOG.append(f"[{ts}] {msg}")
        if len(EVENT_LOG) > MAX_LOG:
            EVENT_LOG.pop(0)


def _parse_date(s: str, ref: date | None = None) -> str | None:
    key = (s or "").strip().lower()
    ref = ref or date.today()
    if key == "today":
        return ref.isoformat()
    if key == "tomorrow":
        return (ref + timedelta(days=1)).isoformat()
    try:
        return date.fromisoformat(s.strip()).isoformat()
    except ValueError:
        return None


def _normalize_time(t: str) -> str | None:
    raw = (t or "").strip().replace(".", ":")
    parts = raw.split(":")
    if len(parts) != 2:
        return None
    try:
        h, m = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return f"{h:02d}:{m:02d}"


def _time_to_minutes(t: str) -> int:
    h, m = map(int, t.split(":"))
    return h * 60 + m


def _ensure_state() -> None:
    with _lock:
        if not PLANNER["selected"]:
            today = date.today()
            PLANNER["selected"] = today.isoformat()
            PLANNER["view_year"] = today.year
            PLANNER["view_month"] = today.month


def add_event(
    title: str,
    date_str: str,
    time_str: str,
    duration_minutes: int = 60,
    category: str = "other",
) -> str:
    """Add a calendar event.

    Args:
        title: Short title shown on the timeline.
        date_str: today, tomorrow, or YYYY-MM-DD.
        time_str: Start time HH:MM (24h).
        duration_minutes: Length in minutes (15-480).
        category: work, personal, health, meeting, or other.
    """
    _ensure_state()
    d = _parse_date(date_str)
    if d is None:
        return f"Invalid date '{date_str}'. Use today, tomorrow, or YYYY-MM-DD."
    t = _normalize_time(time_str)
    if t is None:
        return f"Invalid time '{time_str}'. Use HH:MM (24h)."
    cat = (category or "other").strip().lower()
    if cat not in CATEGORIES:
        return f"Invalid category '{category}'. Use: {', '.join(CATEGORIES)}."
    dur = max(15, min(480, int(duration_minutes)))
    ttl = (title or "").strip()
    if not ttl:
        return "Title is required."

    with _lock:
        eid = PLANNER["next_id"]
        PLANNER["next_id"] += 1
        PLANNER["events"].append(
            {
                "id": eid,
                "title": ttl,
                "date": d,
                "time": t,
                "duration_minutes": dur,
                "category": cat,
                "reminder_before": None,
                "flash_until": time.monotonic() + 1.6,
            }
        )
        PLANNER["selected"] = d
        y, m, _ = map(int, d.split("-"))
        PLANNER["view_year"], PLANNER["view_month"] = y, m
    _log(f"+ {ttl} @ {d} {t} ({dur}m, {cat})")
    return f"Added '{ttl}' on {d} at {t} for {dur} minutes ({cat})."


def remove_event(title: str) -> str:
    """Remove the first event whose title matches (case-insensitive).

    Args:
        title: Event title to remove.
    """
    key = (title or "").strip().lower()
    if not key:
        return "Title is required."
    with _lock:
        for i, ev in enumerate(PLANNER["events"]):
            if ev["title"].strip().lower() == key:
                removed = PLANNER["events"].pop(i)
                _log(f"- {removed['title']}")
                return f"Removed event '{removed['title']}'."
    return f"No event titled '{title}'."


def update_event(
    title: str,
    new_title: str = "",
    new_date: str = "",
    new_time: str = "",
    new_duration_minutes: int = -1,
    new_category: str = "",
) -> str:
    """Update fields on the first event matching title. Leave a field unchanged by passing empty or -1 for duration.

    Args:
        title: Current title to find.
        new_title: New title, or empty to keep.
        new_date: today / tomorrow / YYYY-MM-DD, or empty to keep.
        new_time: HH:MM, or empty to keep.
        new_duration_minutes: New duration, or -1 to keep.
        new_category: work/personal/health/meeting/other, or empty to keep.
    """
    key = (title or "").strip().lower()
    if not key:
        return "title is required to find the event."
    nd = _parse_date(new_date) if (new_date or "").strip() else None
    if (new_date or "").strip() and nd is None:
        return f"Invalid new_date '{new_date}'."
    nt = _normalize_time(new_time) if (new_time or "").strip() else None
    if (new_time or "").strip() and nt is None:
        return f"Invalid new_time '{new_time}'."
    nc = (new_category or "").strip().lower()
    if nc and nc not in CATEGORIES:
        return f"Invalid new_category '{new_category}'."

    with _lock:
        ev = next((e for e in PLANNER["events"] if e["title"].strip().lower() == key), None)
        if ev is None:
            return f"No event titled '{title}'."
        if (new_title or "").strip():
            ev["title"] = new_title.strip()
        if nd is not None:
            ev["date"] = nd
        if nt is not None:
            ev["time"] = nt
        if new_duration_minutes >= 0:
            ev["duration_minutes"] = max(15, min(480, int(new_duration_minutes)))
        if nc:
            ev["category"] = nc
        ev["flash_until"] = time.monotonic() + 1.4
        PLANNER["selected"] = ev["date"]
        y, m, _ = map(int, ev["date"].split("-"))
        PLANNER["view_year"], PLANNER["view_month"] = y, m
    _log(f"~ {ev['title']}")
    return (
        f"Updated event: {ev['title']} on {ev['date']} at {ev['time']} ({ev['duration_minutes']}m, {ev['category']})."
    )


def get_schedule(date_str: str) -> str:
    """Focus the planner on a date and return that day's events as text.

    Args:
        date_str: today, tomorrow, or YYYY-MM-DD.
    """
    _ensure_state()
    d = _parse_date(date_str)
    if d is None:
        return f"Invalid date '{date_str}'."
    with _lock:
        PLANNER["selected"] = d
        y, m, _ = map(int, d.split("-"))
        PLANNER["view_year"], PLANNER["view_month"] = y, m
        day_events = [e for e in PLANNER["events"] if e["date"] == d]
        day_events.sort(key=lambda e: e["time"])
        lines = [f"{e['time']}  {e['title']}  ({e['duration_minutes']}m, {e['category']})" for e in day_events]
        body = "\n".join(lines) if lines else "(no events)"
        PLANNER["last_query"] = body
    _log(f"? schedule {d}")
    return f"Schedule for {d}:\n{body}"


def clear_schedule(date_str: str = "") -> str:
    """Clear events for one day, or all events if date is empty or 'all'.

    Args:
        date_str: today, tomorrow, YYYY-MM-DD, empty, or all.
    """
    key = (date_str or "").strip().lower()
    with _lock:
        if not key or key == "all":
            n = len(PLANNER["events"])
            PLANNER["events"].clear()
            _log("cleared ALL")
            return f"Cleared all events ({n} removed)."
        d = _parse_date(date_str)
        if d is None:
            return f"Invalid date '{date_str}'. Use today, tomorrow, YYYY-MM-DD, or leave empty for all."
        before = len(PLANNER["events"])
        PLANNER["events"][:] = [e for e in PLANNER["events"] if e["date"] != d]
        removed = before - len(PLANNER["events"])
        _log(f"cleared {d} ({removed})")
        return f"Cleared {removed} event(s) on {d}."


def set_reminder(title: str, minutes_before: int = 15) -> str:
    """Attach a reminder (minutes before start) to the first matching event.

    Args:
        title: Event title to match.
        minutes_before: How many minutes before start (1-180).
    """
    key = (title or "").strip().lower()
    if not key:
        return "Title is required."
    mb = max(1, min(180, int(minutes_before)))
    with _lock:
        for ev in PLANNER["events"]:
            if ev["title"].strip().lower() == key:
                ev["reminder_before"] = mb
                ev["flash_until"] = time.monotonic() + 1.2
                _log(f"bell {ev['title']} -{mb}m")
                return f"Reminder set for '{ev['title']}': {mb} minutes before start."
    return f"No event titled '{title}'."


# ── tkinter GUI (youthful pastel tones; contrasts with dark Smart Home) ──

COL_BG = "#f8f6ff"
COL_PANEL = "#ffffff"
COL_PANEL_DEEP = "#f0ecfb"
COL_BORDER = "#e4dff5"
COL_TEXT = "#4c1d95"
COL_DIM = "#8b7ec8"
COL_ACCENT = "#ec4899"
COL_ACCENT_SOFT = "#fce7f3"
COL_TODAY = "#db2777"
COL_SELECTED = "#fef9c3"
COL_HAS_EVENT = "#eef2ff"
COL_LOG_BG = "#ffffff"
COL_TIMELINE = "#fdfbff"
COL_TIMELINE_GRID = "#ede9fe"
COL_EVENT_TEXT = "#312e81"
COL_FLASH = "#f472b6"
COL_CONNECTED = "#059669"
COL_CONNECTING = "#ea580c"


class PlannerGUI:
    REFRESH_MS = 400

    def __init__(self, root, agent) -> None:
        """Build the planner UI on an existing ``Tk`` root and connected ``YumiAgent``.

        Call ``init_yumi()`` from the process entrypoint (e.g. ``__main__.py``) *after* creating
        the root window, matching other Yumi edge templates and keeping SDK init out of app code.
        """
        import tkinter as tk

        self._tk = tk
        self._root = root
        self._agent = agent

        _ensure_state()
        with _lock:
            vy, vm = PLANNER["view_year"], PLANNER["view_month"]
        self._month_label: tk.Label | None = None
        self._day_cells: list[tk.Label] = []
        self._timeline: tk.Canvas | None = None
        self._log_label: tk.Label | None = None
        self._edge_status: tk.Label | None = None

        self._build_ui(vy, vm)
        self._refresh()

    def _build_ui(self, vy: int, vm: int) -> None:
        tk = self._tk
        r = self._root

        accent = tk.Frame(r, bg=COL_ACCENT, height=5)
        accent.grid(row=0, column=0, columnspan=2, sticky="ew")

        title = tk.Label(
            r,
            text="Yumi Planner",
            font=("Helvetica", 22, "bold"),
            bg=COL_BG,
            fg=COL_TEXT,
        )
        r.columnconfigure(0, weight=0)
        r.columnconfigure(1, weight=1)
        title.grid(row=1, column=0, sticky="w", padx=20, pady=(16, 2))
        tk.Label(
            r,
            text="Day timeline",
            font=("Helvetica", 11),
            bg=COL_BG,
            fg=COL_DIM,
        ).grid(row=1, column=1, sticky="e", padx=20, pady=(16, 2))

        self._edge_status = tk.Label(
            r,
            text="Connecting · Planner-Demo · 6 tools",
            font=("Helvetica", 10, "bold"),
            bg=COL_BG,
            fg=COL_CONNECTING,
        )
        self._edge_status.grid(row=2, column=0, columnspan=2, sticky="w", padx=20, pady=(0, 4))

        sub = tk.Label(
            r,
            text="Display only. Chat controls this app + Smart Home in one session (hardware vs software).",
            font=("Helvetica", 10),
            bg=COL_BG,
            fg=COL_DIM,
            wraplength=900,
            justify="left",
        )
        sub.grid(row=3, column=0, columnspan=2, sticky="w", padx=20, pady=(0, 10))

        left = tk.Frame(r, bg=COL_PANEL, highlightbackground=COL_BORDER, highlightthickness=1, width=248)
        left.grid(row=4, column=0, sticky="nsew", padx=(20, 10), pady=6)
        left.grid_propagate(False)

        nav = tk.Frame(left, bg=COL_PANEL)
        nav.pack(fill="x", padx=10, pady=(12, 8))
        btn_kw = {
            "font": ("Helvetica", 13, "bold"),
            "width": 2,
            "bg": COL_ACCENT_SOFT,
            "fg": COL_ACCENT,
            "activebackground": COL_PANEL_DEEP,
            "activeforeground": COL_ACCENT,
            "relief": "flat",
            "borderwidth": 0,
            "cursor": "hand2",
        }
        tk.Button(nav, text="\u2039", command=self._prev_month, **btn_kw).pack(side="left")
        self._month_label = tk.Label(nav, text="", font=("Helvetica", 13, "bold"), bg=COL_PANEL, fg=COL_TEXT)
        self._month_label.pack(side="left", expand=True)
        tk.Button(nav, text="\u203a", command=self._next_month, **btn_kw).pack(side="right")

        hdr = tk.Frame(left, bg=COL_PANEL)
        hdr.pack(fill="x", padx=6)
        for wd in ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"):
            tk.Label(hdr, text=wd, width=4, font=("Helvetica", 9, "bold"), bg=COL_PANEL, fg=COL_DIM).pack(side="left")

        grid = tk.Frame(left, bg=COL_PANEL)
        grid.pack(fill="both", expand=True, padx=6, pady=(4, 12))
        for _ in range(42):
            lb = tk.Label(
                grid,
                text="",
                width=4,
                height=1,
                font=("Helvetica", 11),
                bg=COL_PANEL,
                fg=COL_TEXT,
                padx=2,
                pady=2,
            )
            r_, c_ = divmod(len(self._day_cells), 7)
            lb.grid(row=r_, column=c_, padx=2, pady=2)
            lb.bind("<Button-1>", self._on_day_click)
            self._day_cells.append(lb)

        right_wrap = tk.Frame(r, bg=COL_BG)
        right_wrap.grid(row=4, column=1, sticky="nsew", padx=(10, 20), pady=6)

        hours = HOUR_END - HOUR_START + 1
        ch = hours * HOUR_PX + 32
        self._timeline = tk.Canvas(
            right_wrap,
            width=660,
            height=ch,
            bg=COL_TIMELINE,
            highlightthickness=1,
            highlightbackground=COL_BORDER,
        )
        self._timeline.pack(fill="both", expand=True)

        log_frame = tk.Frame(r, bg=COL_LOG_BG, highlightbackground=COL_BORDER, highlightthickness=1)
        log_frame.grid(row=5, column=0, columnspan=2, padx=20, pady=(8, 4), sticky="ew")

        tk.Label(
            log_frame,
            text="Activity",
            font=("Helvetica", 9, "bold"),
            bg=COL_LOG_BG,
            fg=COL_DIM,
            anchor="w",
        ).pack(fill="x", padx=12, pady=(8, 0))
        self._log_label = tk.Label(
            log_frame,
            text="Waiting for AI commands…",
            font=("Courier", 10),
            bg=COL_LOG_BG,
            fg=COL_DIM,
            justify="left",
            anchor="w",
        )
        self._log_label.pack(fill="x", padx=12, pady=(2, 10))

        tk.Label(
            r,
            text="Tools: add_event · remove_event · update_event · get_schedule · clear_schedule · set_reminder",
            font=("Helvetica", 9),
            bg=COL_BG,
            fg=COL_DIM,
        ).grid(row=6, column=0, columnspan=2, sticky="w", padx=20, pady=(0, 14))

    def _prev_month(self) -> None:
        with _lock:
            y, m = PLANNER["view_year"], PLANNER["view_month"]
            m -= 1
            if m < 1:
                m, y = 12, y - 1
            PLANNER["view_month"], PLANNER["view_year"] = m, y

    def _next_month(self) -> None:
        with _lock:
            y, m = PLANNER["view_year"], PLANNER["view_month"]
            m += 1
            if m > 12:
                m, y = 1, y + 1
            PLANNER["view_month"], PLANNER["view_year"] = m, y

    def _on_day_click(self, event) -> None:
        w = event.widget
        txt = w.cget("text")
        if not txt.isdigit():
            return
        day = int(txt)
        with _lock:
            y, m = PLANNER["view_year"], PLANNER["view_month"]
            try:
                d = date(y, m, day)
            except ValueError:
                return
            PLANNER["selected"] = d.isoformat()
            _log(f"pick {d.isoformat()}")

    def _paint_calendar(self) -> None:
        with _lock:
            y, m = PLANNER["view_year"], PLANNER["view_month"]
            sel = PLANNER["selected"]
            ev_dates = {e["date"] for e in PLANNER["events"]}

        if self._month_label:
            self._month_label.config(text=f"{calendar.month_name[m]} {y}")

        first = date(y, m, 1).weekday()  # Mon=0
        _, n_days = calendar.monthrange(y, m)
        today = date.today().isoformat()

        for i, lb in enumerate(self._day_cells):
            lb.unbind("<Button-1>")
            day_num = i - first + 1
            if day_num < 1 or day_num > n_days:
                lb.config(text="", bg=COL_PANEL_DEEP, fg=COL_DIM)
                continue
            d_iso = date(y, m, day_num).isoformat()
            lb.config(text=str(day_num))
            has = d_iso in ev_dates
            is_sel = d_iso == sel
            is_today = d_iso == today
            if is_sel:
                bg = COL_SELECTED
            elif has:
                bg = COL_HAS_EVENT
            else:
                bg = COL_PANEL
            fg = COL_TODAY if is_today else COL_TEXT
            font = ("Helvetica", 11, "bold") if is_today else ("Helvetica", 11)
            lb.config(bg=bg, fg=fg, cursor="hand2", font=font)
            lb.bind("<Button-1>", self._on_day_click)

    def _paint_timeline(self) -> None:
        c = self._timeline
        if not c:
            return
        c.delete("all")
        w = int(c.cget("width"))
        pad_l = 52
        pad_top = 8
        inner_w = w - pad_l - 12

        ch_canvas = int(c.cget("height"))
        c.create_rectangle(0, 0, w, ch_canvas, fill=COL_TIMELINE, outline=COL_TIMELINE)
        for h in range(HOUR_START, HOUR_END + 1):
            y = pad_top + (h - HOUR_START) * HOUR_PX
            c.create_line(pad_l, y, w - 10, y, fill=COL_TIMELINE_GRID)
            c.create_text(10, y + 2, anchor="nw", text=f"{h:02d}:00", fill=COL_DIM, font=("Helvetica", 9))

        with _lock:
            sel = PLANNER["selected"]
            events = [dict(e) for e in PLANNER["events"] if e["date"] == sel]
        events.sort(key=lambda e: e["time"])

        # simple overlap columns
        cols: list[list[dict]] = []
        for ev in events:
            start = _time_to_minutes(ev["time"])
            end = start + int(ev["duration_minutes"])
            placed = False
            for col in cols:
                ok = True
                for other in col:
                    os_ = _time_to_minutes(other["time"])
                    oe = os_ + int(other["duration_minutes"])
                    if not (end <= os_ or start >= oe):
                        ok = False
                        break
                if ok:
                    col.append(ev)
                    ev["_col"] = cols.index(col)
                    placed = True
                    break
            if not placed:
                ev["_col"] = len(cols)
                cols.append([ev])
        ncols = max(1, len(cols))
        col_w = inner_w / ncols

        now = time.monotonic()
        for ev in events:
            col = ev.get("_col", 0)
            start = _time_to_minutes(ev["time"])
            day_start = HOUR_START * 60
            day_end = (HOUR_END + 1) * 60
            if start < day_start:
                start = day_start
            if start >= day_end:
                continue
            end = min(_time_to_minutes(ev["time"]) + int(ev["duration_minutes"]), day_end)
            y0 = pad_top + (start - HOUR_START * 60) / 60.0 * HOUR_PX
            y1 = pad_top + (end - HOUR_START * 60) / 60.0 * HOUR_PX
            x0 = pad_l + col * col_w + 4
            x1 = pad_l + (col + 1) * col_w - 4
            color = CAT_COLORS.get(ev["category"], CAT_COLORS["other"])
            flash = ev.get("flash_until", 0) and now < ev["flash_until"]
            outline = COL_FLASH if flash else COL_BORDER
            width = 3 if flash else 1
            c.create_rectangle(x0, y0, x1, y1, fill=color, outline=outline, width=width)
            title = ev["title"]
            if len(title) > 28:
                title = title[:26] + "…"
            c.create_text(x0 + 8, y0 + 5, anchor="nw", text=title, fill=COL_EVENT_TEXT, font=("Helvetica", 9, "bold"))
            c.create_text(
                x0 + 8,
                y0 + 20,
                anchor="nw",
                text=f"{ev['time']} · {ev['duration_minutes']}m",
                fill=COL_EVENT_TEXT,
                font=("Helvetica", 8),
            )
            if ev.get("reminder_before") is not None:
                c.create_text(x1 - 8, y0 + 5, anchor="ne", text="\u23f0", fill=COL_EVENT_TEXT, font=("Helvetica", 11))

    def _refresh(self) -> None:
        self._paint_calendar()
        self._paint_timeline()

        with _lock:
            log_copy = list(EVENT_LOG)

        if self._log_label:
            if log_copy:
                self._log_label.config(text="\n".join(log_copy), fg=COL_TEXT)
            else:
                self._log_label.config(text="Waiting for AI commands…", fg=COL_DIM)

        if self._agent and self._edge_status:
            connected = (
                self._agent._thread is not None
                and self._agent._thread.is_alive()
                and not self._agent._stop_event.is_set()
            )
            n = len(self._agent._tools)
            edge_name = getattr(self._agent, "_edge_name", "Planner-Demo")
            if connected:
                self._edge_status.config(text=f"Connected · {edge_name} · {n} tools", fg=COL_CONNECTED)
            else:
                self._edge_status.config(text=f"Connecting · {edge_name} · {n} tools", fg=COL_CONNECTING)

        self._root.after(self.REFRESH_MS, self._refresh)

    def run(self) -> None:
        self._root.mainloop()
