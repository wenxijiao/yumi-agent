"""Narrow, structured playback contract for the Room Control music tools.

Transport success or model text is never evidence that music actually started.
Other tool schemas can adopt this contract explicitly as integrations are added.
"""

from __future__ import annotations

import json

MUSIC_TOOLS = {"music_play", "music_play_request", "music_enqueue", "music_control", "music_stop"}


def playback_feedback(inv, result) -> dict:
    name = inv.original_tool_name or inv.func_name
    if name not in MUSIC_TOOLS:
        return {}
    if result.status != "success":
        return {"media_playback": "unknown"}
    try:
        payload = json.loads(result.result)
    except (ValueError, TypeError):
        return {"media_playback": "unknown"}
    if not isinstance(payload, dict) or payload.get("ok") is not True or payload.get("error"):
        return {"media_playback": "unknown"}
    playback = payload.get("playback")
    if not isinstance(playback, dict):
        return {"media_playback": "unknown"}
    state = playback.get("state")
    if not isinstance(state, str) or state not in {"playing", "paused", "stopped"}:
        return {"media_playback": "unknown"}
    return {"media_playback": state}
