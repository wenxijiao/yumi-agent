"""Plugin port definitions.

Each ``Protocol`` describes one extension point that the OSS core calls into
during normal request handling. The OSS ships trivial single-user defaults in
:mod:`kumi.core.plugins.single_user`; commercial / enterprise builds register
richer implementations via :func:`kumi.core.plugins.register_plugin`.

The OSS core MUST only depend on these abstractions — never import anything
from a commercial package directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from kumi.core.plugins.identity import Identity

if TYPE_CHECKING:
    from fastapi import FastAPI
    from kumi.core.chatbot import KumiBot
    from kumi.core.memories.memory import Memory


@runtime_checkable
class IdentityProvider(Protocol):
    """Resolve the request-scoped :class:`Identity`."""

    def current(self) -> Identity:
        """Return the identity bound to the current async context."""

    def from_request(self, request: Any) -> Identity | None:
        """Best-effort identity from an incoming HTTP/WS request (default: ``None``)."""


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
    """Map raw client session ids to storage session ids (per-user prefix in MT)."""

    def qualify_session_id(self, identity: Identity, client_session_id: str | None) -> str: ...
    def qualify_session_http(self, identity: Identity, client_session_id: str | None) -> str: ...
    def owner_user_from_session_id(self, session_id: str) -> str: ...
    def session_id_prefix_for_identity(self, identity: Identity) -> str | None: ...
    def ensure_session_owned_by_identity(self, identity: Identity, sid: str) -> None: ...
    def ensure_message_owned_by_identity(self, identity: Identity, message: dict) -> None: ...


@runtime_checkable
class BotPool(Protocol):
    """Per-user :class:`KumiBot` resolution (returns the shared singleton in OSS)."""

    async def get_bot_for_identity(self, identity: Identity) -> "KumiBot": ...
    async def get_bot_for_session_owner(self, owner_user_id: str) -> "KumiBot": ...
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
    """Edge connection key / tool prefix scoping (per-user in MT, plain in OSS).

    The two lifecycle hooks (``on_edge_register`` / ``on_edge_disconnect``) let
    enterprise plugins observe the WebSocket lifecycle without changing the
    OSS edge protocol or message shapes. The OSS calls them at the natural
    points in ``handle_edge_peer``; the default implementations do nothing.
    """

    def connection_key(self, owner_user_id: str | None, edge_name: str) -> str: ...
    def tool_register_prefix(self, owner_user_id: str | None, edge_name: str) -> str: ...
    def filter_edge_tool_schemas(
        self,
        identity: Identity,
        registry: dict[str, dict],
        disabled: set[str],
    ) -> list: ...

    def on_edge_register(self, connection_key: str, auth_msg: dict) -> None:
        """Called once after a successful edge register handshake.

        ``auth_msg`` is the raw register payload (``edge_name``, ``tools``,
        ``access_token``, etc.). Default: no-op.
        """

    def on_edge_disconnect(self, connection_key: str) -> None:
        """Called when an edge connection is being torn down. Default: no-op."""


@runtime_checkable
class AuditSink(Protocol):
    """Audit logging hook (logs only in OSS, also persists in enterprise)."""

    def event(self, event: str, user_id: str | None = None, **fields: object) -> None: ...


@runtime_checkable
class SystemPromptExtender(Protocol):
    """Inject extra blocks into the chat system prompt.

    The composed prompt for a turn is built in fixed layers::

        DEFAULT_SYSTEM_PROMPT  (L1 OSS — identity, language, tone, honesty)
        + plugin sections      (L2 tenant info, L3 brand / app context, …)
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
    """Mount additional FastAPI routes (admin, auth, relay)."""

    def mount(self, app: "FastAPI") -> None: ...


@runtime_checkable
class MiddlewareExtender(Protocol):
    """Return additional ASGI middleware classes to wrap the FastAPI app."""

    def middlewares(self) -> list: ...


@runtime_checkable
class AdminCli(Protocol):
    """Inject extra CLI subcommands into ``kumi-enterprise`` (no-op for ``kumi``)."""

    def add_arguments(self, parser: Any) -> None: ...
    def handle(self, args: Any) -> bool:
        """Handle parsed ``args``. Return True if a command was dispatched."""
