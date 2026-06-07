"""Edge connection handling extracted from api.py."""

from copy import deepcopy

from fastapi import WebSocketDisconnect
from kumi.core.api.peers import EdgePeerDisconnected
from kumi.core.api.state import (
    ACTIVE_CONNECTIONS,
    ALWAYS_ALLOWED_TOOLS,
    CONFIRMATION_TOOLS,
    EDGE_TOOLS_REGISTRY,
    PENDING_EDGE_OPS,
    PENDING_TOOL_CALLS,
    edge_tool_key_prefix,
    edge_tool_register_prefix,
    logger,
    parse_edge_connection_key,
)
from kumi.core.features.config import load_saved_model_config, save_model_config
from kumi.core.platform.plugins import get_edge_scope
from kumi.core.platform.tools.tool import TOOL_REGISTRY

# ── edge tool confirmation helpers ──


def _clear_edge_confirmation_state_for_prefix(tool_prefix: str) -> None:
    for s in list(ALWAYS_ALLOWED_TOOLS):
        if s.startswith(tool_prefix):
            ALWAYS_ALLOWED_TOOLS.discard(s)
    for s in list(CONFIRMATION_TOOLS):
        if s.startswith(tool_prefix):
            CONFIRMATION_TOOLS.discard(s)


def apply_edge_tool_confirmation_policy(tool_prefix: str, policy: dict | None) -> None:
    _clear_edge_confirmation_state_for_prefix(tool_prefix)
    if not policy:
        return
    prefix = tool_prefix
    for t in policy.get("always_allow") or []:
        if isinstance(t, str) and t:
            ALWAYS_ALLOWED_TOOLS.add(f"{prefix}{t}")
    for t in policy.get("force_confirm") or []:
        if isinstance(t, str) and t:
            CONFIRMATION_TOOLS.add(f"{prefix}{t}")


def apply_local_tool_confirmation_from_saved_config() -> None:
    cfg = load_saved_model_config()
    names = set(TOOL_REGISTRY.keys())
    always = set(cfg.local_tools_always_allow)
    for n in always:
        if n in names:
            ALWAYS_ALLOWED_TOOLS.add(n)
    for n in cfg.local_tools_force_confirm:
        if n in names:
            CONFIRMATION_TOOLS.add(n)
    # Apply per-tool default-confirmation unless the user has explicitly opted into always-allow.
    for tool_name, entry in TOOL_REGISTRY.items():
        if entry.get("default_require_confirmation") and tool_name not in always:
            CONFIRMATION_TOOLS.add(tool_name)


def persist_local_tool_confirmation_to_config() -> None:
    config = load_saved_model_config()
    local = set(TOOL_REGISTRY.keys())
    config.local_tools_always_allow = sorted(n for n in ALWAYS_ALLOWED_TOOLS if n in local)
    config.local_tools_force_confirm = sorted(n for n in CONFIRMATION_TOOLS if n in local)
    save_model_config(config)


async def push_confirmation_policy_to_edge(connection_key: str) -> None:
    peer = ACTIVE_CONNECTIONS.get(connection_key)
    if peer is None:
        return
    owner_id, edge_simple = parse_edge_connection_key(connection_key)
    tool_prefix = (
        edge_tool_register_prefix(owner_id, edge_simple)
        if owner_id
        else edge_tool_key_prefix(edge_simple or connection_key)
    )
    await _push_confirmation_policy_to_edge_peer(peer, connection_key, tool_prefix)


async def _push_confirmation_policy_to_edge_peer(peer, connection_key: str, tool_prefix: str) -> None:
    tools_dict = EDGE_TOOLS_REGISTRY.get(connection_key) or {}
    prefix = tool_prefix
    always: list[str] = []
    force: list[str] = []
    for full in tools_dict:
        if not full.startswith(prefix):
            continue
        short = full[len(prefix) :]
        if full in ALWAYS_ALLOWED_TOOLS:
            always.append(short)
        if full in CONFIRMATION_TOOLS:
            force.append(short)
    try:
        await peer.send_json(
            {
                "type": "persist_tool_confirmation_policy",
                "always_allow": always,
                "force_confirm": force,
            }
        )
    except Exception as exc:
        logger.debug("Could not push tool confirmation policy to edge %s: %s", connection_key, exc)


# ── edge connection cleanup ──


def cleanup_edge_connection(connection_key: str, peer):
    if ACTIVE_CONNECTIONS.get(connection_key) is peer:
        del ACTIVE_CONNECTIONS[connection_key]
        EDGE_TOOLS_REGISTRY.pop(connection_key, None)
        try:
            get_edge_scope().on_edge_disconnect(connection_key)
        except Exception as exc:
            logger.debug("EdgeScope.on_edge_disconnect raised: %s", exc)

    for call_id, pending in list(PENDING_TOOL_CALLS.items()):
        if pending["edge_name"] != connection_key or pending["peer"] is not peer:
            continue
        future = pending["future"]
        if not future.done():
            future.set_exception(ConnectionError(f"Edge device '{connection_key}' disconnected during tool execution."))
        PENDING_TOOL_CALLS.pop(call_id, None)

    for op_id, pending in list(PENDING_EDGE_OPS.items()):
        if pending["edge_name"] != connection_key or pending["peer"] is not peer:
            continue
        future = pending["future"]
        if not future.done():
            future.set_exception(ConnectionError(f"Edge device '{connection_key}' disconnected."))
        PENDING_EDGE_OPS.pop(op_id, None)


# ── main edge peer loop ──


async def handle_edge_peer(peer):
    """OSS edge peer loop: LAN-only, no per-user tenancy.

    Enterprise builds wrap this loop (or replace ``ws/edge`` entirely) to add
    user-token verification and per-owner connection key scoping.
    """
    edge_name = "Unknown"
    connection_key = "Unknown"
    tool_prefix = ""

    try:
        auth_msg = await peer.receive_json()
        if auth_msg.get("type") != "register":
            raise ValueError("Expected a register message from the edge client.")

        edge_name = auth_msg.get("edge_name", "Unknown_Edge")
        connection_key = edge_name
        tool_prefix = edge_tool_key_prefix(edge_name)

        tools = auth_msg.get("tools", [])
        previous_peer = ACTIVE_CONNECTIONS.get(connection_key)

        if previous_peer is not None and previous_peer is not peer:
            logger.info("Edge device [%s] reconnected; replacing old socket.", edge_name)
            for call_id, pending in list(PENDING_TOOL_CALLS.items()):
                if pending["edge_name"] == connection_key and pending["peer"] is previous_peer:
                    try:
                        await previous_peer.send_json({"type": "cancel", "call_id": call_id})
                    except Exception as cancel_exc:
                        logger.debug("Cancel in-flight tool on edge reconnect: %s", cancel_exc)
                    future = pending["future"]
                    if not future.done():
                        future.set_exception(
                            ConnectionError(f"Edge device '{edge_name}' reconnected; stale call cancelled.")
                        )
                    PENDING_TOOL_CALLS.pop(call_id, None)
            await previous_peer.close(code=1012, reason="Replaced by a newer connection")

        ACTIVE_CONNECTIONS[connection_key] = peer
        EDGE_TOOLS_REGISTRY[connection_key] = {}

        for tool_schema in tools:
            original_name = tool_schema["function"]["name"]
            prefixed_name = f"{tool_prefix}{original_name}"
            schema_copy = deepcopy(tool_schema)
            schema_copy["function"]["name"] = prefixed_name
            tool_timeout = schema_copy.pop("timeout", None)
            require_confirmation = bool(schema_copy.pop("require_confirmation", False))
            always_include = bool(schema_copy.pop("always_include", False))
            allow_proactive = bool(schema_copy.pop("allow_proactive", False))
            proactive_context = bool(schema_copy.pop("proactive_context", False))
            proactive_context_args = schema_copy.pop("proactive_context_args", None)
            proactive_context_description = schema_copy.pop("proactive_context_description", None)
            EDGE_TOOLS_REGISTRY[connection_key][prefixed_name] = {
                "schema": schema_copy,
                "timeout": tool_timeout,
                "require_confirmation": require_confirmation,
                "always_include": always_include,
                "allow_proactive": allow_proactive,
                "proactive_context": proactive_context,
                "proactive_context_args": proactive_context_args if isinstance(proactive_context_args, dict) else None,
                "proactive_context_description": proactive_context_description,
            }

        apply_edge_tool_confirmation_policy(
            tool_prefix,
            auth_msg.get("tool_confirmation_policy"),
        )

        try:
            get_edge_scope().on_edge_register(connection_key, auth_msg)
        except Exception as exc:
            logger.debug("EdgeScope.on_edge_register raised: %s", exc)

        logger.info("Edge connected: device [%s] with %s mounted tools.", edge_name, len(tools))

        while True:
            data = await peer.receive_json()
            msg_type = data.get("type")

            if msg_type == "tool_result":
                call_id = data.get("call_id")
                result = data.get("result")
                pending = PENDING_TOOL_CALLS.pop(call_id, None)
                if pending:
                    future = pending["future"]
                    if not future.done():
                        future.set_result(result)

            elif msg_type == "file_op_result":
                op_id = data.get("op_id")
                pending = PENDING_EDGE_OPS.pop(op_id, None)
                if pending:
                    future = pending["future"]
                    if not future.done():
                        if "error" in data:
                            future.set_exception(ValueError(data["error"]))
                        else:
                            future.set_result(data.get("data", {}))

            elif msg_type == "update_tools":
                tools = data.get("tools", [])
                EDGE_TOOLS_REGISTRY[connection_key] = {}
                for tool_schema in tools:
                    original_name = tool_schema["function"]["name"]
                    prefixed_name = f"{tool_prefix}{original_name}"
                    schema_copy = deepcopy(tool_schema)
                    schema_copy["function"]["name"] = prefixed_name
                    tool_timeout = schema_copy.pop("timeout", None)
                    require_confirmation = bool(schema_copy.pop("require_confirmation", False))
                    always_include = bool(schema_copy.pop("always_include", False))
                    allow_proactive = bool(schema_copy.pop("allow_proactive", False))
                    proactive_context = bool(schema_copy.pop("proactive_context", False))
                    proactive_context_args = schema_copy.pop("proactive_context_args", None)
                    proactive_context_description = schema_copy.pop("proactive_context_description", None)
                    EDGE_TOOLS_REGISTRY[connection_key][prefixed_name] = {
                        "schema": schema_copy,
                        "timeout": tool_timeout,
                        "require_confirmation": require_confirmation,
                        "always_include": always_include,
                        "allow_proactive": allow_proactive,
                        "proactive_context": proactive_context,
                        "proactive_context_args": proactive_context_args
                        if isinstance(proactive_context_args, dict)
                        else None,
                        "proactive_context_description": proactive_context_description,
                    }
                apply_edge_tool_confirmation_policy(
                    tool_prefix,
                    data.get("tool_confirmation_policy"),
                )
                logger.info("Edge updated: device [%s] now has %s tool(s).", edge_name, len(tools))

    except (WebSocketDisconnect, EdgePeerDisconnected):
        logger.info("Edge disconnected: device [%s] went offline.", edge_name)
        cleanup_edge_connection(connection_key, peer)
    except Exception:
        logger.exception("Edge error: device [%s] failed", edge_name)
        cleanup_edge_connection(connection_key, peer)
