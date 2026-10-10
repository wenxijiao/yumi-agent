"""Read-only Room Control playback monitoring, bound to a completed chat turn.

No model calls, client-selected tool names, URLs, or playback commands. The
binding is persisted with the trace so reconnects and API restarts can recover.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import HTTPException
from yumi.core.platform.dispatch.context import ToolInvocation
from yumi.core.platform.dispatch.edge import EdgeToolExecutor
from yumi.core.platform.plugins import get_edge_scope
from yumi.core.platform.tools.visibility import model_disabled_tools


def watch_binding(invocations, runtime) -> dict | None:
    # This integration's music_status contract is explicitly read-only. Do not
    # generalize the name convention to arbitrary terminal actions.
    if len(invocations) != 1:
        return None
    inv = invocations[0]
    if inv.kind != "edge" or inv.original_tool_name not in {"music_play", "music_play_request"} or not inv.target_edge:
        return None
    name = inv.func_name.removesuffix(inv.original_tool_name) + "music_status"
    meta = runtime.edge_registry.tools.get(inv.target_edge, {}).get(name)
    if not meta or meta.get("require_confirmation"):
        return None
    if meta.get("schema", {}).get("function", {}).get("parameters", {}).get("required"):
        return None
    return {"edge": inv.target_edge, "tool": name}


def _authorized_target(identity, trace, runtime):
    binding = trace.get("media_watch")
    if not isinstance(binding, dict):
        raise HTTPException(404, "This turn has no playback monitor.")
    edge, name = binding.get("edge"), binding.get("tool")
    meta = runtime.edge_registry.tools.get(edge, {}).get(name)
    peer = runtime.edge_registry.active_connections.get(edge)
    if not peer or not meta:
        return None
    disabled = model_disabled_tools(identity, runtime.tool_policy.disabled_tools, session_id=trace["session_id"])
    visible = get_edge_scope().filter_edge_tool_schemas(identity, runtime.edge_registry.tools, disabled)
    if name not in {s["function"]["name"] for s in visible}:
        raise HTTPException(403, "Playback status is no longer accessible.")
    from yumi.core.platform.runtime.assistant_context import personal_store
    from yumi.core.platform.storage.assistant_store import is_personal_session

    own = (
        personal_store(identity.user_id).get("tools", {}).get(name, {})
        if is_personal_session(trace["session_id"])
        else {}
    )
    if (
        meta.get("require_confirmation")
        or name in runtime.tool_policy.confirmation_tools
        or own.get("require_confirmation")
        or own.get("ai_access") == "ask"
    ):
        raise HTTPException(403, "Playback status requires confirmation; use the app.")
    return ToolInvocation(
        kind="edge",
        func_name=name,
        tool_message_name=name,
        args={},
        target_edge=edge,
        original_tool_name="music_status",
        peer=peer,
        caller_user_id=identity.user_id,
    )


@dataclass
class _Sample:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    sampled_at: float = float("-inf")
    state: str = "unknown"


_samples: OrderedDict[tuple, _Sample] = OrderedDict()


async def playback_state(identity, trace, runtime) -> dict:
    if trace.get("owner_user_id") != identity.user_id:
        raise HTTPException(404, "Playback monitor not found.")
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(trace["started_at"])).total_seconds()
    except (ValueError, KeyError, TypeError):
        raise HTTPException(410, "Playback monitor expired.") from None
    if age > 86400 or age < -60:
        raise HTTPException(410, "Playback monitor expired.")
    inv = _authorized_target(identity, trace, runtime)
    if inv is None:
        return {"state": "unknown"}
    # Recheck permissions even for cached samples. Serialize duplicate clients
    # and bound cache size; two-second reads do not consume model tokens.
    key = (id(runtime), identity.user_id, trace["id"])
    sample = _samples.setdefault(key, _Sample())
    _samples.move_to_end(key)
    while len(_samples) > 512:
        _samples.popitem(last=False)
    async with sample.lock:
        if time.monotonic() - sample.sampled_at >= 2:
            sample.state = "unknown"
            try:
                result = await asyncio.wait_for(EdgeToolExecutor(runtime, default_timeout=6).run(inv), timeout=6)
                payload = json.loads(result.result)
                if (
                    result.status == "success"
                    and isinstance(payload, dict)
                    and payload.get("ok") is True
                    and not payload.get("error")
                ):
                    playback = payload.get("playback")
                    state = playback.get("state") if isinstance(playback, dict) else None
                    if state == "playing":
                        sample.state = "playing"
                    elif isinstance(playback, dict) and state in {"paused", "stopped"}:
                        sample.state = (
                            "ended" if playback.get("queue") == [] and not playback.get("song") else "inactive"
                        )
            except (asyncio.TimeoutError, ValueError, TypeError):
                pass
            sample.sampled_at = time.monotonic()
        return {"state": sample.state}
