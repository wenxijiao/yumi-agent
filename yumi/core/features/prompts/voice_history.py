"""Keep song references in voice history without replaying artwork and device dumps."""

from __future__ import annotations

import json


def compact_voice_history(messages: list[dict]) -> list[dict]:
    """Only transform previous music tool snapshots; preserve stored history.

    Keep every candidate and its ID in order so "the third one" still resolves.
    Current-turn results never pass through this function.
    """
    calls = {
        call.get("id"): call.get("function", {}).get("name", "")
        for message in messages
        for call in message.get("tool_calls", [])
        if isinstance(call, dict)
    }
    result = []
    for message in messages:
        name = str(message.get("name") or calls.get(message.get("tool_call_id")) or "").rsplit("__", 1)[-1]
        if message.get("role") != "tool" or name not in {
            "music_search",
            "music_play",
            "music_play_request",
            "music_enqueue",
            "music_status",
            "music_control",
            "music_stop",
        }:
            result.append(message)
            continue
        try:
            payload = json.loads(message.get("content", ""))
        except (TypeError, ValueError):
            result.append(message)
            continue
        if not isinstance(payload, dict):
            result.append(message)
            continue

        def song(value):
            if not isinstance(value, dict):
                return value
            return {k: v for k, v in value.items() if k in {"id", "title", "artist", "album", "duration"}}

        compact = {k: v for k, v in payload.items() if k in {"ok", "error", "status", "played", "message"}}
        compact["historical_snapshot"] = True
        if isinstance(payload.get("songs"), list):
            compact["songs"] = [song(s) for s in payload["songs"]]
        if isinstance(payload.get("playback"), dict):
            playback = payload["playback"]
            compact["playback"] = {k: v for k, v in playback.items() if k in {"state", "position"}}
            if "song" in playback:
                compact["playback"]["song"] = song(playback["song"])
            if isinstance(playback.get("queue"), list):
                compact["playback"]["queue"] = [song(s) for s in playback["queue"]]
        if isinstance(payload.get("lights"), dict):
            compact["lights"] = {k: v for k, v in payload["lights"].items() if k in {"active", "source"}}
        result.append({**message, "content": json.dumps(compact, ensure_ascii=False, separators=(",", ":"))})
    return result
