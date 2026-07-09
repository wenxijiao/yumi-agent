"""discover_app_tools — the model's escape hatch out of sticky tool routing.

With sticky routing (``edge_tools_routing_mode="sticky"``) only the edges a
session actually uses stay attached to the request, so the tools array — part
of the provider's cached prompt prefix — barely ever changes. The trade-off is
discoverability: the model can't call what it can't see. This meta tool closes
that gap: given a natural-language need it ranks ALL connected edge tools,
ACTIVATES the best edge for the session (sticky), and returns the matches.
The activated tools become callable in the SAME turn via the chat loop's
append-only forced-tools mechanism (which preserves the already-sent prefix).
"""

from __future__ import annotations

import json

from yumi.core.platform.plugins import get_current_identity
from yumi.core.platform.runtime import get_default_runtime
from yumi.core.platform.tools.routing import activate_edge_for_session, search_edge_tools
from yumi.logging_config import get_logger

logger = get_logger(__name__)


def discover_app_tools(need: str, session_id: str = "default") -> str:
    """Find tools on the user's connected apps/devices that can fulfil a need,
    and make the best-matching app's tools available in this conversation.

    Args:
        need: What you're trying to do, in natural language.
        session_id: Leave default; the server stamps the current session.
    """
    need = (need or "").strip()
    if not need:
        return json.dumps({"ok": False, "error": "need is required"})

    runtime = get_default_runtime()
    matches = search_edge_tools(
        need,
        identity=get_current_identity(),
        disabled_tools=runtime.tool_policy.disabled_tools,
        edge_registry=runtime.edge_registry.tools,
        limit=12,
    )
    if not matches:
        return json.dumps(
            {
                "ok": True,
                "matches": [],
                "note": "no connected app exposes tools for this — answer directly or tell the user",
            }
        )

    # Activate the top match's edge for the whole session, and hand back every
    # sibling tool name on that edge so the caller (chat service) can expose
    # the full kit for the rest of this turn.
    top_edge = matches[0].get("edge_key") or ""
    activated_tool_names: list[str] = []
    if top_edge:
        activate_edge_for_session(session_id, top_edge)
        edge_tools = runtime.edge_registry.tools.get(top_edge) or {}
        activated_tool_names = sorted(edge_tools.keys())
        logger.info(
            "discover_app_tools activated edge %r (%d tools) for session %s",
            top_edge,
            len(activated_tool_names),
            session_id,
        )

    return json.dumps(
        {
            "ok": True,
            "matches": [
                {k: m[k] for k in ("name", "description", "device") if m.get(k) is not None} for m in matches[:8]
            ],
            "activated_device": matches[0].get("device") or "",
            "activated_tool_names": activated_tool_names,
            "note": "the activated device's tools are available from now on — call them directly",
        },
        ensure_ascii=False,
    )
