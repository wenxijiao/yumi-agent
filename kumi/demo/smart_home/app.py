"""Kumi Smart Home Simulator — state and tool functions.

This module represents the "user's application". It contains all the
home state and the functions that control the devices. These functions
are imported by ``smart_home/setup.py`` and registered with the Kumi SDK,
just like a real user would do in their own project.

Run with: ``python -m kumi.demo.smart_home`` or ``kumi --demo``. ``init_kumi()`` is
invoked from ``__main__.py``, not from this module.
"""

from __future__ import annotations

import threading
import tkinter as tk
from datetime import datetime

# ── shared state ──

_lock = threading.Lock()

HOME: dict = {
    "living_room": {
        "light": {"on": False, "brightness": 80},
        "tv": {"on": False, "channel": "ESPN"},
        "speaker": {"on": False, "song": "Jazz"},
    },
    "kitchen": {
        "light": {"on": False, "brightness": 100},
        "oven": {"on": False, "temperature": 180},
        "coffee": {"status": "idle"},
    },
    "bedroom": {
        "lamp": {"on": False, "brightness": 60},
        "curtains": {"position": "closed"},
        "alarm": {"time": "off"},
    },
    "bathroom": {
        "light": {"on": False, "brightness": 100},
        "fan": {"on": False},
        "heater": {"on": False, "temperature": 40},
    },
    "garden": {
        "sprinkler": {"on": False},
        "porch_light": {"on": False},
        "gate": {"position": "closed"},
    },
    "system": {
        "thermostat": {"temperature": 22},
        "door_lock": {"locked": True},
    },
}

EVENT_LOG: list[str] = []
MAX_LOG = 8


def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    with _lock:
        EVENT_LOG.append(f"[{ts}] {msg}")
        if len(EVENT_LOG) > MAX_LOG:
            EVENT_LOG.pop(0)


# ── 14 tool functions ──


def set_light(room: str, on: bool, brightness: int = 100) -> str:
    """Turn a room light on/off and set brightness (0-100).

    Args:
        room: One of living_room, kitchen, bedroom, bathroom.
        on: True to turn on, False to turn off.
        brightness: Brightness percentage 0-100.
    """
    room = room.lower().replace(" ", "_")
    key = "lamp" if room == "bedroom" else "light"
    target = HOME.get(room, {}).get(key)
    if target is None:
        return f"No light found in '{room}'"
    with _lock:
        target["on"] = on
        target["brightness"] = max(0, min(100, brightness))
    state = f"ON ({target['brightness']}%)" if on else "OFF"
    _log(f"{room} light -> {state}")
    return f"{room} light is now {state}"


def set_tv(on: bool, channel: str = "ESPN") -> str:
    """Turn the living room TV on/off and set the channel.

    Args:
        on: True to turn on, False to turn off.
        channel: Channel name to display.
    """
    tv = HOME["living_room"]["tv"]
    with _lock:
        tv["on"] = on
        if channel:
            tv["channel"] = channel
    state = f"ON ({tv['channel']})" if on else "OFF"
    _log(f"TV -> {state}")
    return f"TV is now {state}"


def set_speaker(on: bool, song: str = "Jazz") -> str:
    """Turn the living room speaker on/off and choose a song/genre.

    Args:
        on: True to turn on, False to turn off.
        song: Song name or genre to play.
    """
    spk = HOME["living_room"]["speaker"]
    with _lock:
        spk["on"] = on
        if song:
            spk["song"] = song
    state = f"Playing {spk['song']}" if on else "OFF"
    _log(f"Speaker -> {state}")
    return f"Speaker is now {state}"


def set_oven(on: bool, temperature: int = 180) -> str:
    """Turn the kitchen oven on/off and set temperature in Celsius.

    Args:
        on: True to turn on, False to turn off.
        temperature: Oven temperature in Celsius (50-300).
    """
    oven = HOME["kitchen"]["oven"]
    with _lock:
        oven["on"] = on
        oven["temperature"] = max(50, min(300, temperature))
    state = f"ON ({oven['temperature']}C)" if on else "OFF"
    _log(f"Oven -> {state}")
    return f"Oven is now {state}"


def brew_coffee(action: str = "start") -> str:
    """Start or stop the coffee machine.

    Args:
        action: "start" to brew coffee, "stop" to stop.
    """
    coffee = HOME["kitchen"]["coffee"]
    with _lock:
        if action.lower() == "start":
            coffee["status"] = "brewing"
        else:
            coffee["status"] = "idle"
    _log(f"Coffee -> {coffee['status']}")
    return f"Coffee machine is now {coffee['status']}"


def set_curtains(position: str = "open") -> str:
    """Open or close the bedroom curtains.

    Args:
        position: "open" or "closed".
    """
    curtains = HOME["bedroom"]["curtains"]
    pos = "open" if position.lower() in ("open", "opened") else "closed"
    with _lock:
        curtains["position"] = pos
    _log(f"Curtains -> {pos}")
    return f"Curtains are now {pos}"


def set_alarm(time: str = "off") -> str:
    """Set or clear the bedroom alarm clock.

    Args:
        time: Alarm time like "7:30", or "off" to disable.
    """
    alarm = HOME["bedroom"]["alarm"]
    with _lock:
        alarm["time"] = time.strip()
    _log(f"Alarm -> {alarm['time']}")
    return f"Alarm is now set to {alarm['time']}"


def set_fan(on: bool) -> str:
    """Turn the bathroom fan on or off.

    Args:
        on: True to turn on, False to turn off.
    """
    fan = HOME["bathroom"]["fan"]
    with _lock:
        fan["on"] = on
    state = "ON" if on else "OFF"
    _log(f"Bathroom fan -> {state}")
    return f"Bathroom fan is now {state}"


def set_water_heater(on: bool, temperature: int = 40) -> str:
    """Turn the bathroom water heater on/off and set temperature.

    Args:
        on: True to turn on, False to turn off.
        temperature: Water temperature in Celsius (30-70).
    """
    heater = HOME["bathroom"]["heater"]
    with _lock:
        heater["on"] = on
        heater["temperature"] = max(30, min(70, temperature))
    state = f"ON ({heater['temperature']}C)" if on else "OFF"
    _log(f"Water heater -> {state}")
    return f"Water heater is now {state}"


def set_sprinkler(on: bool) -> str:
    """Turn the garden sprinkler on or off.

    Args:
        on: True to turn on, False to turn off.
    """
    sprinkler = HOME["garden"]["sprinkler"]
    with _lock:
        sprinkler["on"] = on
    state = "ON" if on else "OFF"
    _log(f"Sprinkler -> {state}")
    return f"Garden sprinkler is now {state}"


def set_porch_light(on: bool) -> str:
    """Turn the garden porch light on or off.

    Args:
        on: True to turn on, False to turn off.
    """
    porch = HOME["garden"]["porch_light"]
    with _lock:
        porch["on"] = on
    state = "ON" if on else "OFF"
    _log(f"Porch light -> {state}")
    return f"Porch light is now {state}"


def set_gate(position: str = "closed") -> str:
    """Open or close the garden gate.

    Args:
        position: "open" or "closed".
    """
    gate = HOME["garden"]["gate"]
    pos = "open" if position.lower() in ("open", "opened") else "closed"
    with _lock:
        gate["position"] = pos
    _log(f"Gate -> {pos}")
    return f"Garden gate is now {pos}"


def set_thermostat(temperature: int) -> str:
    """Set the whole-house thermostat temperature in Celsius.

    Args:
        temperature: Target temperature (10-35).
    """
    thermo = HOME["system"]["thermostat"]
    with _lock:
        thermo["temperature"] = max(10, min(35, temperature))
    _log(f"Thermostat -> {thermo['temperature']}C")
    return f"Thermostat set to {thermo['temperature']}C"


def set_door_lock(locked: bool) -> str:
    """Lock or unlock the front door.

    Args:
        locked: True to lock, False to unlock.
    """
    door = HOME["system"]["door_lock"]
    with _lock:
        door["locked"] = locked
    state = "LOCKED" if locked else "UNLOCKED"
    _log(f"Front door -> {state}")
    return f"Front door is now {state}"


# ── tkinter GUI ──

COL_BG = "#1e1e2e"
COL_CARD = "#2a2a3c"
COL_CARD_BORDER = "#3a3a4c"
COL_TEXT = "#cdd6f4"
COL_DIM = "#6c7086"
COL_ON = "#a6e3a1"
COL_OFF = "#585b70"
COL_ACCENT = "#89b4fa"
COL_WARM = "#fab387"
COL_YELLOW = "#f9e2af"
COL_RED = "#f38ba8"
COL_GREEN = "#a6e3a1"
COL_LOG_BG = "#232334"


class SmartHomeGUI:
    REFRESH_MS = 500

    def __init__(self, agent=None):
        self._agent = agent
        self._root = tk.Tk()
        self._root.title("Kumi Smart Home Simulator")
        self._root.configure(bg=COL_BG)
        self._root.resizable(False, False)

        self._labels: dict[str, tk.Label] = {}
        self._indicators: dict[str, tk.Canvas] = {}

        self._build_ui()
        self._refresh()

    def _build_ui(self):
        r = self._root

        title = tk.Label(
            r,
            text="Kumi Smart Home",
            font=("Helvetica", 20, "bold"),
            bg=COL_BG,
            fg=COL_ACCENT,
        )
        title.grid(row=0, column=0, columnspan=3, pady=(16, 4), sticky="w", padx=20)

        self._edge_status_label = tk.Label(
            r,
            text="Connecting · SmartHome-Demo · 14 tools",
            font=("Helvetica", 10, "bold"),
            bg=COL_BG,
            fg=COL_WARM,
        )
        self._edge_status_label.grid(row=1, column=0, columnspan=3, sticky="w", padx=20, pady=(0, 4))

        subtitle = tk.Label(
            r,
            text=("Display only. Use kumi --chat or kumi --ui to control Smart Home and Planner in one conversation."),
            font=("Helvetica", 10),
            bg=COL_BG,
            fg=COL_DIM,
            wraplength=880,
            justify="left",
        )
        subtitle.grid(row=2, column=0, columnspan=3, sticky="w", padx=20, pady=(0, 12))

        rooms = [
            ("Living Room", self._build_living_room, 0),
            ("Kitchen", self._build_kitchen, 1),
            ("Bedroom", self._build_bedroom, 2),
            ("Bathroom", self._build_bathroom, 0),
            ("Garden", self._build_garden, 1),
            ("System", self._build_system, 2),
        ]

        for i, (name, builder, col) in enumerate(rooms):
            row_offset = 3 if i < 3 else 5
            frame = self._make_card(r, name)
            frame.grid(row=row_offset, column=col, padx=10, pady=6, sticky="nsew")
            builder(frame)

        for c in range(3):
            r.columnconfigure(c, weight=1, minsize=260)

        log_frame = tk.Frame(r, bg=COL_LOG_BG, highlightbackground=COL_CARD_BORDER, highlightthickness=1)
        log_frame.grid(row=7, column=0, columnspan=3, padx=10, pady=(8, 4), sticky="ew")

        log_title = tk.Label(
            log_frame,
            text="Activity Log",
            font=("Helvetica", 10, "bold"),
            bg=COL_LOG_BG,
            fg=COL_DIM,
            anchor="w",
        )
        log_title.pack(fill="x", padx=10, pady=(6, 2))

        self._log_label = tk.Label(
            log_frame,
            text="Waiting for agent commands...",
            font=("Courier", 10),
            bg=COL_LOG_BG,
            fg=COL_DIM,
            justify="left",
            anchor="w",
        )
        self._log_label.pack(fill="x", padx=10, pady=(0, 8))

        status_frame = tk.Frame(r, bg=COL_BG)
        status_frame.grid(row=8, column=0, columnspan=3, padx=20, pady=(4, 14), sticky="ew")

        self._clock_label = tk.Label(
            status_frame,
            text="",
            font=("Helvetica", 10),
            bg=COL_BG,
            fg=COL_DIM,
            anchor="e",
        )
        self._clock_label.pack(side="right")

    def _make_card(self, parent, title: str) -> tk.Frame:
        outer = tk.Frame(parent, bg=COL_CARD, highlightbackground=COL_CARD_BORDER, highlightthickness=1)
        header = tk.Label(
            outer,
            text=title,
            font=("Helvetica", 12, "bold"),
            bg=COL_CARD,
            fg=COL_TEXT,
            anchor="w",
        )
        header.pack(fill="x", padx=12, pady=(10, 4))

        sep = tk.Frame(outer, bg=COL_CARD_BORDER, height=1)
        sep.pack(fill="x", padx=12, pady=(0, 6))

        return outer

    def _add_row(self, parent, key: str, label: str, has_indicator: bool = True):
        row = tk.Frame(parent, bg=COL_CARD)
        row.pack(fill="x", padx=12, pady=2)

        if has_indicator:
            canvas = tk.Canvas(row, width=12, height=12, bg=COL_CARD, highlightthickness=0)
            canvas.pack(side="left", padx=(0, 6))
            canvas.create_oval(2, 2, 12, 12, fill=COL_OFF, outline="", tags="dot")
            self._indicators[key] = canvas

        name_lbl = tk.Label(
            row,
            text=label,
            font=("Helvetica", 10),
            bg=COL_CARD,
            fg=COL_DIM,
            width=10,
            anchor="w",
        )
        name_lbl.pack(side="left")

        val_lbl = tk.Label(
            row,
            text="OFF",
            font=("Helvetica", 10, "bold"),
            bg=COL_CARD,
            fg=COL_OFF,
            anchor="w",
        )
        val_lbl.pack(side="left", fill="x", expand=True)
        self._labels[key] = val_lbl

    def _build_living_room(self, frame):
        self._add_row(frame, "lr_light", "Light")
        self._add_row(frame, "lr_tv", "TV")
        self._add_row(frame, "lr_speaker", "Speaker")
        tk.Frame(frame, bg=COL_CARD, height=6).pack()

    def _build_kitchen(self, frame):
        self._add_row(frame, "ki_light", "Light")
        self._add_row(frame, "ki_oven", "Oven")
        self._add_row(frame, "ki_coffee", "Coffee")
        tk.Frame(frame, bg=COL_CARD, height=6).pack()

    def _build_bedroom(self, frame):
        self._add_row(frame, "br_lamp", "Lamp")
        self._add_row(frame, "br_curtains", "Curtains")
        self._add_row(frame, "br_alarm", "Alarm")
        tk.Frame(frame, bg=COL_CARD, height=6).pack()

    def _build_bathroom(self, frame):
        self._add_row(frame, "ba_light", "Light")
        self._add_row(frame, "ba_fan", "Fan")
        self._add_row(frame, "ba_heater", "Heater")
        tk.Frame(frame, bg=COL_CARD, height=6).pack()

    def _build_garden(self, frame):
        self._add_row(frame, "ga_sprinkler", "Sprinkler")
        self._add_row(frame, "ga_porch", "Porch Light")
        self._add_row(frame, "ga_gate", "Gate")
        tk.Frame(frame, bg=COL_CARD, height=6).pack()

    def _build_system(self, frame):
        self._add_row(frame, "sys_thermo", "Thermostat")
        self._add_row(frame, "sys_door", "Front Door")
        tk.Frame(frame, bg=COL_CARD, height=26).pack()

    def _set_val(self, key: str, text: str, is_on: bool):
        lbl = self._labels.get(key)
        if lbl:
            lbl.config(text=text, fg=COL_ON if is_on else COL_OFF)
        ind = self._indicators.get(key)
        if ind:
            ind.delete("dot")
            color = COL_GREEN if is_on else COL_OFF
            ind.create_oval(2, 2, 12, 12, fill=color, outline="", tags="dot")

    def _refresh(self):
        with _lock:
            lr = HOME["living_room"]
            ki = HOME["kitchen"]
            br = HOME["bedroom"]
            ba = HOME["bathroom"]
            ga = HOME["garden"]
            sy = HOME["system"]

            lr_l = lr["light"]
            self._set_val("lr_light", f"ON ({lr_l['brightness']}%)" if lr_l["on"] else "OFF", lr_l["on"])

            tv = lr["tv"]
            self._set_val("lr_tv", tv["channel"] if tv["on"] else "OFF", tv["on"])

            spk = lr["speaker"]
            self._set_val("lr_speaker", f"♪ {spk['song']}" if spk["on"] else "OFF", spk["on"])

            ki_l = ki["light"]
            self._set_val("ki_light", f"ON ({ki_l['brightness']}%)" if ki_l["on"] else "OFF", ki_l["on"])

            ov = ki["oven"]
            self._set_val("ki_oven", f"{ov['temperature']}°C" if ov["on"] else "OFF", ov["on"])

            cof = ki["coffee"]
            is_brewing = cof["status"] == "brewing"
            self._set_val("ki_coffee", "Brewing..." if is_brewing else "Idle", is_brewing)

            bl = br["lamp"]
            self._set_val("br_lamp", f"ON ({bl['brightness']}%)" if bl["on"] else "OFF", bl["on"])

            cur = br["curtains"]
            cur_open = cur["position"] == "open"
            self._set_val("br_curtains", "Open" if cur_open else "Closed", cur_open)

            alm = br["alarm"]
            alm_on = alm["time"] != "off"
            self._set_val("br_alarm", alm["time"] if alm_on else "Off", alm_on)

            ba_l = ba["light"]
            self._set_val("ba_light", f"ON ({ba_l['brightness']}%)" if ba_l["on"] else "OFF", ba_l["on"])
            self._set_val("ba_fan", "ON" if ba["fan"]["on"] else "OFF", ba["fan"]["on"])

            ht = ba["heater"]
            self._set_val("ba_heater", f"{ht['temperature']}°C" if ht["on"] else "OFF", ht["on"])

            self._set_val("ga_sprinkler", "ON" if ga["sprinkler"]["on"] else "OFF", ga["sprinkler"]["on"])
            self._set_val("ga_porch", "ON" if ga["porch_light"]["on"] else "OFF", ga["porch_light"]["on"])

            gt = ga["gate"]
            gt_open = gt["position"] == "open"
            self._set_val("ga_gate", "Open" if gt_open else "Closed", gt_open)

            self._set_val("sys_thermo", f"{sy['thermostat']['temperature']}°C", True)

            locked = sy["door_lock"]["locked"]
            door_lbl = self._labels.get("sys_door")
            if door_lbl:
                door_lbl.config(
                    text="Locked" if locked else "Unlocked",
                    fg=COL_RED if locked else COL_GREEN,
                )
            door_ind = self._indicators.get("sys_door")
            if door_ind:
                door_ind.delete("dot")
                door_ind.create_oval(2, 2, 12, 12, fill=COL_RED if locked else COL_GREEN, outline="", tags="dot")

            log_copy = list(EVENT_LOG)

        if log_copy:
            self._log_label.config(text="\n".join(log_copy), fg=COL_TEXT)
        else:
            self._log_label.config(text="Waiting for agent commands...", fg=COL_DIM)

        now = datetime.now().strftime("%H:%M:%S")
        self._clock_label.config(text=now)

        if self._agent:
            connected = (
                self._agent._thread is not None
                and self._agent._thread.is_alive()
                and not self._agent._stop_event.is_set()
            )
            n = len(self._agent._tools)
            edge_name = getattr(self._agent, "_edge_name", "SmartHome-Demo")
            if connected:
                self._edge_status_label.config(text=f"Connected · {edge_name} · {n} tools", fg=COL_GREEN)
            else:
                self._edge_status_label.config(text=f"Connecting · {edge_name} · {n} tools", fg=COL_WARM)

        self._root.after(self.REFRESH_MS, self._refresh)

    def run(self):
        self._root.mainloop()
