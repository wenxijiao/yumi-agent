"""Tests for the plugin port registry and its single-user (OSS) defaults.

The registry is a process-global singleton (``yumi.core.platform.plugins.registry``)
whose accessors return the OSS default unless a plugin overrides a port via
:func:`register_plugin`. These tests assert the default wiring, the
per-port replacement semantics, and the behaviour of each single-user default.

Every test that mutates the registry restores the original ports via the
``restore_registry`` fixture so global state never leaks across tests.
"""

from __future__ import annotations

import pytest
from yumi.core.platform.plugins import (
    LOCAL_IDENTITY,
    SINGLE_USER_ID,
    Identity,
    get_admin_cli,
    get_audit_sink,
    get_billing_hook,
    get_bot_pool,
    get_current_identity,
    get_edge_scope,
    get_identity_provider,
    get_memory_factory,
    get_middleware_extender,
    get_quota_policy,
    get_route_extender,
    get_session_scope,
    get_system_prompt_extender,
    register_plugin,
    reset_current_identity,
    set_current_identity,
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

_ALL_GETTERS = {
    "identity_provider": get_identity_provider,
    "quota_policy": get_quota_policy,
    "billing_hook": get_billing_hook,
    "session_scope": get_session_scope,
    "bot_pool": get_bot_pool,
    "memory_factory": get_memory_factory,
    "edge_scope": get_edge_scope,
    "audit_sink": get_audit_sink,
    "route_extender": get_route_extender,
    "middleware_extender": get_middleware_extender,
    "admin_cli": get_admin_cli,
    "system_prompt_extender": get_system_prompt_extender,
}


@pytest.fixture
def restore_registry():
    """Snapshot every port before the test and re-register them afterwards."""
    snapshot = {name: getter() for name, getter in _ALL_GETTERS.items()}
    yield
    register_plugin(**snapshot)


# ── default wiring ──────────────────────────────────────────────────────────


def test_defaults_are_single_user_implementations():
    assert isinstance(get_identity_provider(), SingleUserIdentityProvider)
    assert isinstance(get_quota_policy(), NoOpQuotaPolicy)
    assert isinstance(get_billing_hook(), ZeroBillingHook)
    assert isinstance(get_session_scope(), PassThroughSessionScope)
    assert isinstance(get_bot_pool(), SharedBotPool)
    assert isinstance(get_memory_factory(), SharedMemoryFactory)
    assert isinstance(get_edge_scope(), FlatEdgeScope)
    assert isinstance(get_audit_sink(), LoggingAuditSink)
    assert isinstance(get_route_extender(), NoOpRouteExtender)
    assert isinstance(get_middleware_extender(), NoOpMiddlewareExtender)
    assert isinstance(get_admin_cli(), NoOpAdminCli)
    assert isinstance(get_system_prompt_extender(), NoOpSystemPromptExtender)


# ── register_plugin semantics ───────────────────────────────────────────────


def test_register_plugin_replaces_only_supplied_ports(restore_registry):
    sentinel = NoOpQuotaPolicy()
    before_billing = get_billing_hook()

    register_plugin(quota_policy=sentinel)

    assert get_quota_policy() is sentinel
    # untouched ports are left exactly as they were
    assert get_billing_hook() is before_billing


def test_register_plugin_later_registration_wins(restore_registry):
    first = NoOpQuotaPolicy()
    second = NoOpQuotaPolicy()

    register_plugin(quota_policy=first)
    register_plugin(quota_policy=second)

    assert get_quota_policy() is second


def test_register_plugin_none_is_a_noop(restore_registry):
    before = get_quota_policy()
    register_plugin(quota_policy=None)
    assert get_quota_policy() is before


# ── single-user defaults ────────────────────────────────────────────────────


def test_identity_provider_returns_local_by_default():
    assert get_current_identity() is LOCAL_IDENTITY
    assert get_identity_provider().from_request(object()) is None


def test_identity_provider_honours_bound_context_identity():
    bound = Identity(user_id="someone", source="plugin")
    token = set_current_identity(bound)
    try:
        assert get_current_identity() is bound
    finally:
        reset_current_identity(token)
    # once reset, falls back to the local identity again
    assert get_current_identity() is LOCAL_IDENTITY


def test_noop_quota_allows_everything():
    policy = NoOpQuotaPolicy()
    assert policy.check_chat_allowed(LOCAL_IDENTITY) == (True, "")
    assert policy.check_token_quota(LOCAL_IDENTITY) == (True, "")
    assert policy.record_chat_turn(LOCAL_IDENTITY) == 0
    assert policy.record_chat_tokens(LOCAL_IDENTITY, 10, 20) is None
    assert policy.chat_quota_snapshot(LOCAL_IDENTITY) == {}


def test_zero_billing_is_free():
    assert ZeroBillingHook().estimate_usd_for_usage("any-model", 1000, 2000) == 0.0


def test_passthrough_session_scope_qualifies_and_owns():
    scope = PassThroughSessionScope()
    assert scope.qualify_session_id(LOCAL_IDENTITY, None) == "default"
    assert scope.qualify_session_id(LOCAL_IDENTITY, "  ") == "default"
    assert scope.qualify_session_id(LOCAL_IDENTITY, " s1 ") == "s1"
    assert scope.owner_user_from_session_id("anything") == SINGLE_USER_ID
    # ownership checks are no-ops in single-user mode (must not raise)
    scope.ensure_session_owned_by_identity(LOCAL_IDENTITY, "s1")
    scope.ensure_message_owned_by_identity(LOCAL_IDENTITY, {"id": 1})


def test_flat_edge_scope_namespacing():
    scope = FlatEdgeScope()
    # no per-user prefix: connection key is the raw edge name
    assert scope.connection_key("ignored-user", "garage") == "garage"
    # register prefix is provider-safe (sanitised + leading non-alnum guarded) and
    # carries a short hash suffix so different raw names can't collide.
    p = scope.tool_register_prefix(None, "my edge!")
    assert p.startswith("edge_my_edge_") and p.endswith("__")
    assert scope.tool_register_prefix(None, "9bot").startswith("edge_e9bot")


def test_flat_edge_scope_filters_disabled_tools():
    registry = {
        "garage": {
            "garage__open": {"schema": {"name": "garage__open"}},
            "garage__close": {"schema": {"name": "garage__close"}},
        }
    }
    schemas = FlatEdgeScope().filter_edge_tool_schemas(LOCAL_IDENTITY, registry, disabled={"garage__close"})
    names = {s["name"] for s in schemas}
    assert names == {"garage__open"}


def test_logging_audit_sink_does_not_raise():
    # OSS audit sink only logs; smoke-test that it accepts arbitrary fields.
    LoggingAuditSink().event("chat_turn", user_id="u1", tokens=42)


def test_noop_extenders_are_inert():
    assert NoOpRouteExtender().mount(object()) is None
    assert NoOpMiddlewareExtender().middlewares() == []
    assert NoOpSystemPromptExtender().extra_system_prompt_sections(LOCAL_IDENTITY) == []
    assert NoOpAdminCli().handle(object()) is False
