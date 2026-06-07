"""Singleton plugin registry.

Each accessor returns either the OSS single-user default or the implementation
registered by an enterprise plugin via :func:`register_plugin`.
"""

from __future__ import annotations

from threading import Lock

from yumi.core.platform.plugins.ports import (
    AdminCli,
    AuditSink,
    BillingHook,
    BotPool,
    EdgeScope,
    IdentityProvider,
    MemoryFactory,
    MiddlewareExtender,
    QuotaPolicy,
    RouteExtender,
    SessionScope,
    SystemPromptExtender,
)
from yumi.core.platform.plugins.single_user import (
    FlatEdgeScope,
    LoggingAuditSink,
    NoOpAdminCli,
    NoOpMiddlewareExtender,
    NoOpQuotaPolicy,
    NoOpRouteExtender,
    NoOpSystemPromptExtender,
    PassThroughSessionScope,
    SharedBotPool,
    SharedMemoryFactory,
    SingleUserIdentityProvider,
    ZeroBillingHook,
)

_lock = Lock()

_identity_provider: IdentityProvider = SingleUserIdentityProvider()
_quota_policy: QuotaPolicy = NoOpQuotaPolicy()
_billing_hook: BillingHook = ZeroBillingHook()
_session_scope: SessionScope = PassThroughSessionScope()
_bot_pool: BotPool = SharedBotPool()
_memory_factory: MemoryFactory = SharedMemoryFactory()
_edge_scope: EdgeScope = FlatEdgeScope()
_audit_sink: AuditSink = LoggingAuditSink()
_route_extender: RouteExtender = NoOpRouteExtender()
_middleware_extender: MiddlewareExtender = NoOpMiddlewareExtender()
_admin_cli: AdminCli = NoOpAdminCli()
_system_prompt_extender: SystemPromptExtender = NoOpSystemPromptExtender()


def register_plugin(
    *,
    identity_provider: IdentityProvider | None = None,
    quota_policy: QuotaPolicy | None = None,
    billing_hook: BillingHook | None = None,
    session_scope: SessionScope | None = None,
    bot_pool: BotPool | None = None,
    memory_factory: MemoryFactory | None = None,
    edge_scope: EdgeScope | None = None,
    audit_sink: AuditSink | None = None,
    route_extender: RouteExtender | None = None,
    middleware_extender: MiddlewareExtender | None = None,
    admin_cli: AdminCli | None = None,
    system_prompt_extender: SystemPromptExtender | None = None,
) -> None:
    """Replace one or more plugin ports with the supplied implementation(s).

    Called once per plugin module — typically from
    ``yumi_enterprise.plugin.register()``. Calling more than once is allowed
    but later registrations win on a per-port basis.
    """
    global _identity_provider, _quota_policy, _billing_hook, _session_scope
    global _bot_pool, _memory_factory, _edge_scope, _audit_sink
    global _route_extender, _middleware_extender, _admin_cli
    global _system_prompt_extender

    with _lock:
        if identity_provider is not None:
            _identity_provider = identity_provider
        if quota_policy is not None:
            _quota_policy = quota_policy
        if billing_hook is not None:
            _billing_hook = billing_hook
        if session_scope is not None:
            _session_scope = session_scope
        if bot_pool is not None:
            _bot_pool = bot_pool
        if memory_factory is not None:
            _memory_factory = memory_factory
        if edge_scope is not None:
            _edge_scope = edge_scope
        if audit_sink is not None:
            _audit_sink = audit_sink
        if route_extender is not None:
            _route_extender = route_extender
        if middleware_extender is not None:
            _middleware_extender = middleware_extender
        if admin_cli is not None:
            _admin_cli = admin_cli
        if system_prompt_extender is not None:
            _system_prompt_extender = system_prompt_extender


def get_identity_provider() -> IdentityProvider:
    return _identity_provider


def get_quota_policy() -> QuotaPolicy:
    return _quota_policy


def get_billing_hook() -> BillingHook:
    return _billing_hook


def get_session_scope() -> SessionScope:
    return _session_scope


def get_bot_pool() -> BotPool:
    return _bot_pool


def get_memory_factory() -> MemoryFactory:
    return _memory_factory


def get_edge_scope() -> EdgeScope:
    return _edge_scope


def get_audit_sink() -> AuditSink:
    return _audit_sink


def get_route_extender() -> RouteExtender:
    return _route_extender


def get_middleware_extender() -> MiddlewareExtender:
    return _middleware_extender


def get_admin_cli() -> AdminCli:
    return _admin_cli


def get_system_prompt_extender() -> SystemPromptExtender:
    return _system_prompt_extender
