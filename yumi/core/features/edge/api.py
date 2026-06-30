"""Edge connection handling extracted from api.py."""

from copy import deepcopy

from fastapi import WebSocketDisconnect
from yumi.core.features.config import load_saved_model_config, save_model_config
from yumi.core.features.edge.peers import EdgePeerDisconnected
from yumi.core.platform.plugins import get_edge_scope
from yumi.core.platform.runtime.accessors import (
    ACTIVE_CONNECTIONS,
    ALWAYS_ALLOWED_TOOLS,
    CONFIRMATION_TOOLS,
    EDGE_TOOLS_REGISTRY,
    PENDING_EDGE_OPS,
    PENDING_TOOL_CALLS,
    edge_connection_key,
    edge_tool_key_prefix,
    edge_tool_register_prefix,
    logger,
    parse_edge_connection_key,
)
from yumi.core.platform.tools.tool import TOOL_REGISTRY
from yumi.core.platform.tools.validation import is_valid_tool_name

# ── edge tool mounting (shared by register + update_tools) ──


def _mount_edge_tools(connection_key: str, tool_prefix: str, tools: list) -> list[str]:
    """Validate + mount an edge's tools into ``EDGE_TOOLS_REGISTRY[connection_key]``.

    A tool whose prefixed (provider-facing) name isn't provider-safe is skipped
    rather than poisoning the whole tools array. Returns the original names of
    any skipped tools so the caller can tell the edge instead of dropping them
    silently. Used by both the initial register and ``update_tools``.
    """
    registry: dict[str, dict] = {}
    skipped: list[str] = []
    for tool_schema in tools:
        original_name = tool_schema["function"]["name"]
        prefixed_name = f"{tool_prefix}{original_name}"
        if not is_valid_tool_name(prefixed_name):
            skipped.append(original_name)
            logger.warning(
                "Edge %s: skipping tool with a provider-invalid name %r "
                "(allowed: letters, digits, '_' or '-'; max 64 chars after the edge prefix).",
                connection_key,
                prefixed_name,
            )
            continue
        schema_copy = deepcopy(tool_schema)
        schema_copy["function"]["name"] = prefixed_name
        proactive_context_args = schema_copy.pop("proactive_context_args", None)
        registry[prefixed_name] = {
            "schema": schema_copy,
            "timeout": schema_copy.pop("timeout", None),
            "require_confirmation": bool(schema_copy.pop("require_confirmation", False)),
            # Optional per-tool entitlement key (popped so it never reaches the LLM
            # schema). A plugin's EdgeScope may use it to gate individual tools by
            # subscription (e.g. an app's Pro-only tools), not just the whole edge.
            "entitlement": schema_copy.pop("entitlement", None),
            "always_include": bool(schema_copy.pop("always_include", False)),
            "allow_proactive": bool(schema_copy.pop("allow_proactive", False)),
            "proactive_context": bool(schema_copy.pop("proactive_context", False)),
            "proactive_context_args": proactive_context_args if isinstance(proactive_context_args, dict) else None,
            "proactive_context_description": schema_copy.pop("proactive_context_description", None),
        }
    EDGE_TOOLS_REGISTRY[connection_key] = registry
    return skipped


async def _warn_edge_skipped_tools(peer, connection_key: str, skipped: list[str]) -> None:
    """Best-effort notice to the edge listing tools that weren't mounted."""
    if not skipped:
        return
    try:
        await peer.send_json(
            {
                "type": "register_warning",
                "reason": "invalid_tool_names",
                "skipped_tools": skipped,
                "message": (
                    "These tools were not mounted: each name (after the edge prefix) must be "
                    "letters/digits/'_'/'-' and <= 64 chars total."
                ),
            }
        )
    except Exception as exc:  # the edge may have gone away
        logger.debug("Edge %s: could not send skipped-tools warning: %s", connection_key, exc)


def _owner_user_id_from_register(auth_msg: dict) -> str | None:
    value = auth_msg.get("owner_user_id")
    if isinstance(value, str):
        value = value.strip()
        if value:
            return value
    return None


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
    """Core edge peer loop: LAN-only, with plugin hooks for extra scoping."""
    edge_name = "Unknown"
    connection_key = "Unknown"
    tool_prefix = ""

    try:
        auth_msg = await peer.receive_json()
        if auth_msg.get("type") != "register":
            raise ValueError("Expected a register message from the edge client.")

        edge_name = auth_msg.get("edge_name", "Unknown_Edge")
        owner_user_id = _owner_user_id_from_register(auth_msg)
        connection_key = edge_connection_key(owner_user_id, edge_name)
        tool_prefix = edge_tool_register_prefix(owner_user_id, edge_name)

        tools = auth_msg.get("tools", [])
        previous_peer = ACTIVE_CONNECTIONS.get(connection_key)

        if previous_peer is not None and previous_peer is not peer:
            # An edge with this name is already connected. Reject the NEW
            # connection and keep the existing one. edge_name is the identity
            # used for tool namespacing and routing, so two different edges must
            # not share it. (This replaces the old "replace the socket" behaviour,
            # which made two same-named edges ping-pong-kick each other on every
            # reconnect.) A genuine reconnect still works: the old socket closing
            # clears ACTIVE_CONNECTIONS, after which the name is free again.
            logger.warning(
                "Rejecting edge connection: name [%s] is already in use by an active edge.",
                edge_name,
            )
            try:
                await peer.send_json(
                    {
                        "type": "register_rejected",
                        "reason": (f"An edge named '{edge_name}' is already connected. Use a unique edge_name."),
                    }
                )
                await peer.close(code=4409, reason="edge_name already in use")
            except Exception as reject_exc:
                logger.debug("Error rejecting duplicate edge connection: %s", reject_exc)
            return

        ACTIVE_CONNECTIONS[connection_key] = peer
        skipped = _mount_edge_tools(connection_key, tool_prefix, tools)
        await _warn_edge_skipped_tools(peer, connection_key, skipped)

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
                skipped = _mount_edge_tools(connection_key, tool_prefix, tools)
                await _warn_edge_skipped_tools(peer, connection_key, skipped)
                apply_edge_tool_confirmation_policy(
                    tool_prefix,
                    data.get("tool_confirmation_policy"),
                )
                logger.info("Edge updated: device [%s] now has %s tool(s).", edge_name, len(tools) - len(skipped))

    except (WebSocketDisconnect, EdgePeerDisconnected):
        logger.info("Edge disconnected: device [%s] went offline.", edge_name)
        cleanup_edge_connection(connection_key, peer)
    except Exception:
        logger.exception("Edge error: device [%s] failed", edge_name)
        cleanup_edge_connection(connection_key, peer)
