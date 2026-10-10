import json
from types import SimpleNamespace

import pytest
from yumi.core.features.chat.media_feedback import playback_feedback
from yumi.core.platform.http.events import ToolStatusEvent


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"ok": True, "playback": {"state": "playing"}}, "playing"),
        ({"ok": True, "playback": {"state": "paused"}}, "paused"),
        ({"ok": False, "error": "MusicKit code 6", "playback": {"state": "playing"}}, "unknown"),
        ({"ok": True, "playback": {"state": "queued"}}, "unknown"),
        ({"ok": True, "playback": {"state": []}}, "unknown"),
        ({"ok": True, "message": "music is playing"}, "unknown"),
        ({"ok": "true", "playback": {"state": "playing"}}, "unknown"),
    ],
)
def test_structured_music_feedback(payload, expected):
    inv = SimpleNamespace(original_tool_name="music_play", func_name="edge_Room__music_play")
    result = SimpleNamespace(status="success", result=json.dumps(payload))
    feedback = playback_feedback(inv, result)
    assert feedback == {"media_playback": expected}
    event = ToolStatusEvent(status="success", content="done", **feedback)
    assert event.model_dump()["media_playback"] == expected


def test_search_and_unrelated_tools_do_not_signal_music_playback():
    for name in ["music_search", "music_status", "set_lights", "pretend_music_play"]:
        inv = SimpleNamespace(original_tool_name=name, func_name=name)
        result = SimpleNamespace(status="success", result='{"ok":true,"playback":{"state":"playing"}}')
        assert playback_feedback(inv, result) == {}
