"""Yumi plugin extension layer.

The core only talks to optional extension capabilities through the ports
defined here. Single-user defaults live in
:mod:`yumi.core.platform.plugins.single_user` and ship with Yumi so the
codebase behaves correctly without any plugin installed.

Plugins register richer implementations via :func:`register_plugin`, typically
driven by the ``yumi.plugins`` entry-point group (see
:func:`load_entry_point_plugins`).
"""

from __future__ import annotations

from yumi.core.platform.plugins.discovery import (
    ENTRY_POINT_GROUP,
    load_entry_point_plugins,
    load_plugin_module,
)
from yumi.core.platform.plugins.identity import (
    LOCAL_IDENTITY,
    SINGLE_USER_ID,
    Identity,
    context_identity,
    has_admin_scope,
    reset_current_identity,
    set_current_identity,
)
from yumi.core.platform.plugins.ports import (
    AdminCli,
    AuditSink,
    BillingHook,
    BotPool,
    BridgeScope,
    EdgeScope,
    IdentityProvider,
    MemoryFactory,
    MiddlewareExtender,
    QuotaPolicy,
    RouteExtender,
    SessionScope,
    SystemPromptExtender,
)
from yumi.core.platform.plugins.registry import (
    get_admin_cli,
    get_audit_sink,
    get_billing_hook,
    get_bot_pool,
    get_bridge_scope,
    get_edge_scope,
    get_identity_provider,
    get_memory_factory,
    get_middleware_extender,
    get_quota_policy,
    get_route_extender,
    get_session_scope,
    get_system_prompt_extender,
    register_plugin,
)


def get_current_identity() -> Identity:
    """Convenience wrapper for ``get_identity_provider().current()``."""
    return get_identity_provider().current()


__all__ = [
    "AdminCli",
    "AuditSink",
    "BillingHook",
    "BotPool",
    "BridgeScope",
    "EdgeScope",
    "ENTRY_POINT_GROUP",
    "Identity",
    "IdentityProvider",
    "LOCAL_IDENTITY",
    "MemoryFactory",
    "MiddlewareExtender",
    "QuotaPolicy",
    "RouteExtender",
    "SINGLE_USER_ID",
    "SessionScope",
    "SystemPromptExtender",
    "context_identity",
    "get_admin_cli",
    "get_audit_sink",
    "get_billing_hook",
    "get_bot_pool",
    "get_bridge_scope",
    "get_current_identity",
    "get_edge_scope",
    "get_identity_provider",
    "get_memory_factory",
    "get_middleware_extender",
    "get_quota_policy",
    "get_route_extender",
    "get_session_scope",
    "get_system_prompt_extender",
    "has_admin_scope",
    "load_entry_point_plugins",
    "load_plugin_module",
    "register_plugin",
    "reset_current_identity",
    "set_current_identity",
]
