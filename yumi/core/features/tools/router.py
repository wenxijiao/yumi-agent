"""Tool listing and policy routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from yumi.core.features.edge.api import persist_local_tool_confirmation_to_config, push_confirmation_policy_to_edge
from yumi.core.platform.http.dependencies import CurrentIdentity
from yumi.core.platform.http.schemas import (
    ToolConfirmationResponse,
    ToolConfirmationToggleRequest,
    ToolToggleRequest,
)
from yumi.core.platform.runtime.accessors import (
    ACTIVE_CONNECTIONS,
    ALWAYS_ALLOWED_TOOLS,
    CONFIRMATION_TOOLS,
    DISABLED_TOOLS,
    EDGE_TOOLS_REGISTRY,
    PENDING_CONFIRMATIONS,
    resolve_edge_for_prefixed_tool_name,
)
from yumi.core.platform.tools.tool import TOOL_REGISTRY

router = APIRouter()


@router.post("/tools/toggle")
async def toggle_tool_endpoint(request: ToolToggleRequest):
    if request.disabled:
        DISABLED_TOOLS.add(request.tool_name)
    else:
        DISABLED_TOOLS.discard(request.tool_name)
    return {"status": "success", "tool_name": request.tool_name, "disabled": request.disabled}


@router.post("/tools/set-confirmation")
async def set_tool_confirmation_endpoint(request: ToolConfirmationToggleRequest):
    if request.require_confirmation:
        ALWAYS_ALLOWED_TOOLS.discard(request.tool_name)
        CONFIRMATION_TOOLS.add(request.tool_name)
    else:
        CONFIRMATION_TOOLS.discard(request.tool_name)
        ALWAYS_ALLOWED_TOOLS.add(request.tool_name)

    edge_name = resolve_edge_for_prefixed_tool_name(request.tool_name)
    if edge_name:
        await push_confirmation_policy_to_edge(edge_name)
    else:
        persist_local_tool_confirmation_to_config()

    return {"status": "success", "tool_name": request.tool_name, "require_confirmation": request.require_confirmation}


@router.post("/tools/confirm")
async def confirm_tool_endpoint(request: ToolConfirmationResponse):
    future = PENDING_CONFIRMATIONS.get(request.call_id)
    if future is None or future.done():
        raise HTTPException(status_code=404, detail="No pending confirmation with that call_id.")
    if request.decision not in ("allow", "deny", "always_allow"):
        raise HTTPException(status_code=400, detail="Decision must be 'allow', 'deny', or 'always_allow'.")
    future.set_result(request.decision)
    return {"status": "success", "call_id": request.call_id, "decision": request.decision}


@router.get("/tools")
async def list_tools_endpoint(identity: CurrentIdentity):  # noqa: ARG001
    server_tools = []
    for name, tool_data in TOOL_REGISTRY.items():
        fn = tool_data["schema"]["function"]
        server_tools.append(
            {
                "name": name,
                "description": fn.get("description", ""),
                "disabled": name in DISABLED_TOOLS,
                "require_confirmation": name in CONFIRMATION_TOOLS and name not in ALWAYS_ALLOWED_TOOLS,
            }
        )

    edge_devices = []
    for edge_name, tools_dict in EDGE_TOOLS_REGISTRY.items():
        tools = []
        for prefixed_name, entry in tools_dict.items():
            fn = entry["schema"]["function"]
            original_name = prefixed_name.split("__", 1)[1] if "__" in prefixed_name else prefixed_name
            intrinsic = bool(entry.get("require_confirmation"))
            tools.append(
                {
                    "name": original_name,
                    "full_name": prefixed_name,
                    "description": fn.get("description", ""),
                    "disabled": prefixed_name in DISABLED_TOOLS,
                    "require_confirmation": (
                        prefixed_name not in ALWAYS_ALLOWED_TOOLS and (prefixed_name in CONFIRMATION_TOOLS or intrinsic)
                    ),
                }
            )
        edge_devices.append(
            {
                "edge_name": edge_name,
                "tools": tools,
                "online": edge_name in ACTIVE_CONNECTIONS,
                "shared": False,
            }
        )

    return {
        "server_tools": server_tools,
        "edge_devices": edge_devices,
        "edge": edge_devices,
        "disabled_tools": list(DISABLED_TOOLS),
        "confirmation_tools": list(CONFIRMATION_TOOLS),
        "always_allowed_tools": list(ALWAYS_ALLOWED_TOOLS),
    }
