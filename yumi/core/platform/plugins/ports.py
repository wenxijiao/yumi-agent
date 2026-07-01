"""Plugin port definitions.

Each ``Protocol`` describes one extension point that the core calls into during
normal request handling. The package ships trivial single-user defaults in
:mod:`yumi.core.platform.plugins.single_user`; optional plugins can register
richer implementations via :func:`yumi.core.platform.plugins.register_plugin`.

The core MUST only depend on these abstractions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from yumi.core.platform.plugins.identity import Identity

if TYPE_CHECKING:
    from fastapi import FastAPI
    from yumi.core.chatbot import YumiBot
    from yumi.core.features.memory.memory import Memory


@runtime_checkable
class IdentityProvider(Protocol):
    """Resolve the request-scoped :class:`Identity`."""

    def current(self) -> Identity:
        """Return the identity bound to the current async context."""

    def from_request(self, request: Any) -> Identity | None:
        """Best-effort identity from an incoming HTTP/WS request (default: ``None``).

        The single-user default returns ``None`` — a personal self-hosted agent
        has one user and authenticates nothing. This hook exists so the same
        request flow can derive an identity differently under other deployment
        models; it is an extension point, not a feature the OSS build omits.
        """


@runtime_checkable
class QuotaPolicy(Protocol):
    """Daily quota / token usage accounting (no-op in OSS)."""

    def check_chat_allowed(self, identity: Identity) -> tuple[bool, str]: ...
    def check_token_quota(self, identity: Identity) -> tuple[bool, str]: ...
    def record_chat_turn(self, identity: Identity) -> int: ...
    def record_chat_tokens(
        self,
        identity: Identity,
        prompt_tokens: int,
        completion_tokens: int,
        *,
        model: str = "unknown",
        kind: str = "chat",
    ) -> None: ...
    def record_embed_tokens(
        self,
        identity: Identity,
        estimated_tokens: int,
        *,
        model: str = "unknown",
    ) -> None: ...
    def chat_quota_snapshot(self, identity: Identity) -> dict: ...


@runtime_checkable
class BillingHook(Protocol):
    """Rough USD estimation hook (returns 0.0 in OSS)."""

    def estimate_usd_for_usage(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> float: ...


@runtime_checkable
class SessionScope(Protocol):
    """Map raw client session ids to storage session ids."""

    def qualify_session_id(self, identity: Identity, client_session_id: str | None) -> str: ...
    def qualify_session_http(self, identity: Identity, client_session_id: str | None) -> str: ...
    def owner_user_from_session_id(self, session_id: str) -> str: ...
    def session_id_prefix_for_identity(self, identity: Identity) -> str | None: ...
    def ensure_session_owned_by_identity(self, identity: Identity, sid: str) -> None: ...
    def ensure_message_owned_by_identity(self, identity: Identity, message: dict) -> None: ...


@runtime_checkable
class BridgeScope(Protocol):
    """Resolve a messaging-bridge user (Telegram / Discord / …) to a Yumi session
    + server connection, and handle ``/link`` account binding.

    This is the single identity insertion point messaging bridges need. The
    single-user default treats the channel user as the only user: the session is
    ``<channel>_<id>`` over the shared connection and ``/link`` is a no-op. An
    identity plugin may map the channel user to an account via a stored binding
    plus one-time link codes, so each account only drives its own edges and
    memory.
    """

    def session_id(self, channel: str, channel_user_id: str) -> str:
        """Yumi session id for a bridge user (default ``<channel>_<id>``)."""
        ...

    def connection(self, channel: str, channel_user_id: str) -> Any:
        """The ``ConnectionConfig`` the bridge uses to reach the API for this user."""
        ...

    def link(self, channel: str, channel_user_id: str, code: str) -> str:
        """Handle ``/link <code>`` and return a user-facing reply."""
        ...


@runtime_checkable
class BotPool(Protocol):
    """Per-user :class:`YumiBot` resolution (returns the shared singleton in OSS)."""

    async def get_bot_for_identity(self, identity: Identity) -> "YumiBot": ...
    async def get_bot_for_session_owner(self, owner_user_id: str) -> "YumiBot": ...
    def invalidate(self, user_id: str) -> None: ...
    def start_idle_sweep(self) -> None: ...


@runtime_checkable
class MemoryFactory(Protocol):
    """LanceDB :class:`Memory` resolution (returns the shared store in OSS)."""

    def get_for_identity(self, identity: Identity) -> "Memory": ...
    def get_for_session_owner(self, owner_user_id: str) -> "Memory": ...
    def assert_quota_for_session(self, session_id: str) -> None: ...
    def invalidate_size_cache(self, user_id: str) -> None: ...


@runtime_checkable
class EdgeScope(Protocol):
    """Edge connection key / tool prefix scoping.

    The two lifecycle hooks (``on_edge_register`` / ``on_edge_disconnect``) let
    plugins observe the WebSocket lifecycle without changing the edge protocol
    or message shapes. The core calls them at the natural points in
    ``handle_edge_peer``; the default implementations do nothing.
    """

    def connection_key(self, owner_user_id: str | None, edge_name: str) -> str: ...
    def tool_register_prefix(self, owner_user_id: str | None, edge_name: str) -> str: ...
    def filter_edge_tool_schemas(
        self,
        identity: Identity,
        registry: dict[str, dict],
        disabled: set[str],
    ) -> list: ...

    def resolve_owner_user_id(self, auth_msg: dict) -> str | None:
        """Resolve the TRUSTED owner user_id for a registering edge from the raw
        register payload, or ``None`` to let the caller fall back to the
        client-supplied ``owner_user_id``.

        Multi-tenant plugins derive it server-side (e.g. by resolving a connection
        code against the store) so edge ownership is not client-asserted. Default:
        ``None`` (single-user / LAN edges keep using the self-declared owner).
        """
        ...

    def on_edge_register(self, connection_key: str, auth_msg: dict) -> None:
        """Called once after a successful edge register handshake.

        ``auth_msg`` is the raw register payload (``edge_name``, ``tools``,
        ``access_token``, etc.). Default: no-op.
        """

    def on_edge_disconnect(self, connection_key: str) -> None:
        """Called when an edge connection is being torn down. Default: no-op."""


@runtime_checkable
class AuditSink(Protocol):
    """Audit logging hook."""

    def event(self, event: str, user_id: str | None = None, **fields: object) -> None: ...


@runtime_checkable
class SystemPromptExtender(Protocol):
    """Inject extra blocks into the chat system prompt.

    The composed prompt for a turn is built in fixed layers::

        DEFAULT_SYSTEM_PROMPT  (core identity, language, tone, honesty)
        + plugin sections      (deployment / app context)
        + user addendum        (what the user wrote via /system set)

    Plugins return zero or more strings; the composer joins them with
    blank lines between blocks. Stay short — every block ships on every
    model turn and eats tokens. Use this for situational context that the
    LLM should always know (who the user is, what app they're on, etc.),
    not for one-off instructions that belong in the user's own addendum.
    """

    def extra_system_prompt_sections(self, identity: "Identity") -> list[str]: ...


@runtime_checkable
class RouteExtender(Protocol):
    """Mount additional FastAPI routes."""

    def mount(self, app: "FastAPI") -> None: ...


@runtime_checkable
class MiddlewareExtender(Protocol):
    """Return additional ASGI middleware classes to wrap the FastAPI app."""

    def middlewares(self) -> list: ...


@runtime_checkable
class AdminCli(Protocol):
    """Inject extra CLI subcommands."""

    def add_arguments(self, parser: Any) -> None: ...
    def handle(self, args: Any) -> bool:
        """Handle parsed ``args``. Return True if a command was dispatched."""
