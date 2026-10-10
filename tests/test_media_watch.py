import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from yumi.core.features.chat import media_watch
from yumi.core.platform.dispatch.context import ToolInvocation
from yumi.core.platform.plugins.identity import LOCAL_IDENTITY
from yumi.core.platform.runtime import RuntimeState


def setup_watch():
    runtime = RuntimeState()
    name = "edge_Room__music_status"
    runtime.edge_registry.tools["Room"] = {
        name: {
            "schema": {
                "type": "function",
                "function": {"name": name, "parameters": {"type": "object", "properties": {}}},
            }
        }
    }
    inv = ToolInvocation(
        kind="edge",
        func_name="edge_Room__music_play",
        tool_message_name="edge_Room__music_play",
        args={},
        original_tool_name="music_play",
        target_edge="Room",
        reply_on_success=False,
    )
    binding = media_watch.watch_binding([inv], runtime)
    trace = {
        "id": "turn",
        "session_id": "test",
        "owner_user_id": LOCAL_IDENTITY.user_id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "media_watch": binding,
    }
    return runtime, trace, inv


def test_watch_is_bound_to_exact_music_device_and_survives_json_storage():
    runtime, trace, inv = setup_watch()
    assert json.loads(json.dumps(trace))["media_watch"] == {"edge": "Room", "tool": "edge_Room__music_status"}
    inv.func_name = "edge_Room__music_play_request"
    inv.original_tool_name = "music_play_request"
    assert media_watch.watch_binding([inv], runtime) == trace["media_watch"]
    assert media_watch.watch_binding([inv, inv], runtime) is None
    inv.original_tool_name = "set_lights"
    assert media_watch.watch_binding([inv], runtime) is None


def test_status_rpc_only_calls_readonly_function_and_caches_result():
    async def run():
        runtime, trace, _ = setup_watch()
        calls = []

        class Peer:
            async def send_json(self, frame):
                calls.append(frame)
                runtime.edge_registry.pending_tool_calls[frame["call_id"]]["future"].set_result(
                    '{"ok":true,"playback":{"state":"playing"}}'
                )

        runtime.edge_registry.active_connections["Room"] = Peer()
        for _ in range(2):
            assert await media_watch.playback_state(LOCAL_IDENTITY, trace, runtime) == {"state": "playing"}
        assert len(calls) == 1
        assert calls[0]["name"] == "music_status" and calls[0]["arguments"] == {}
        assert calls[0]["caller_user_id"] == LOCAL_IDENTITY.user_id
        runtime.tool_policy.disabled_tools.add("edge_Room__music_status")
        with pytest.raises(HTTPException) as error:
            await media_watch.playback_state(LOCAL_IDENTITY, trace, runtime)
        assert error.value.status_code == 403
        assert len(calls) == 1

    asyncio.run(run())


@pytest.mark.parametrize("case", ["owner", "expired", "confirmation", "scope", "offline"])
def test_monitor_permissions_and_offline_are_not_finished(monkeypatch, case):
    async def run():
        runtime, trace, _ = setup_watch()
        runtime.edge_registry.active_connections["Room"] = object()
        code = 403
        if case == "owner":
            trace["owner_user_id"] = "someone-else"
            code = 404
        elif case == "expired":
            trace["started_at"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
            code = 410
        elif case == "confirmation":
            runtime.tool_policy.confirmation_tools.add("edge_Room__music_status")
        elif case == "scope":
            monkeypatch.setattr(
                media_watch, "get_edge_scope", lambda: SimpleNamespace(filter_edge_tool_schemas=lambda *a: [])
            )
        else:
            runtime.edge_registry.active_connections.clear()
            assert await media_watch.playback_state(LOCAL_IDENTITY, trace, runtime) == {"state": "unknown"}
            return
        with pytest.raises(HTTPException) as error:
            await media_watch.playback_state(LOCAL_IDENTITY, trace, runtime)
        assert error.value.status_code == code

    asyncio.run(run())
