import copy
import json

from yumi.core.features.prompts.voice_history import compact_voice_history
from yumi.core.platform.tools.retrieval import capability_query


def test_music_history_keeps_all_ordered_song_references_and_errors_without_mutating_storage():
    songs = [
        {
            "id": str(i),
            "title": f"Track {i}",
            "artist": "Artist",
            "album": "Album",
            "duration": 180,
            "artworkURL": "https://example.test/" + "x" * 1000,
        }
        for i in range(8)
    ]
    payload = {
        "ok": True,
        "songs": songs,
        "lights": {"active": False, "source": "playback", "status": "stale description"},
    }
    messages = [
        {"role": "user", "content": "play that one"},
        {"role": "assistant", "tool_calls": [{"id": "search", "function": {"name": "edge_Room__music_search"}}]},
        {"role": "tool", "tool_call_id": "search", "content": json.dumps(payload)},
        {"role": "tool", "name": "edge_Room__music_play", "content": '{"ok":false,"error":"code 6"}'},
        {"role": "tool", "name": "get_weather", "content": "unrelated"},
    ]
    original = copy.deepcopy(messages)
    compact = compact_voice_history(messages)
    assert original == messages
    data = json.loads(compact[2]["content"])
    assert data["historical_snapshot"] is True
    assert [s["id"] for s in data["songs"]] == [str(i) for i in range(8)]
    assert all("artworkURL" not in s for s in data["songs"])
    assert json.loads(compact[3]["content"])["error"] == "code 6"
    assert compact[-1] == messages[-1]
    assert len(compact[2]["content"]) < len(messages[2]["content"]) / 4


def test_japanese_listening_request_has_offline_music_routing_terms():
    for query in ["それ、夜にかけるを聞きたい。", "曲を流して", "音楽を聴きたい", "ききたい"]:
        assert "music song search play" in capability_query(query)
