"""Default single-user implementations of every plugin port.

These ship with OSS so the codebase has zero behavioural dependency on
external extensions. Plugins can override each port via
:func:`yumi.core.platform.plugins.register_plugin` at import time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import HTTPException
from yumi.core.platform.plugins.identity import LOCAL_IDENTITY, SINGLE_USER_ID, Identity, context_identity
from yumi.logging_config import get_logger

if TYPE_CHECKING:
    from fastapi import FastAPI
    from yumi.core.chatbot import YumiBot
    from yumi.core.features.memory.memory import Memory

_log = get_logger(__name__)


class SingleUserIdentityProvider:
    def current(self) -> Identity:
        bound = context_identity()
        return bound if bound is not None else LOCAL_IDENTITY

    def from_request(self, request: Any) -> Identity | None:  # noqa: ARG002
        return None


class NoOpQuotaPolicy:
    def check_chat_allowed(self, identity: Identity) -> tuple[bool, str]:  # noqa: ARG002
        return True, ""

    def check_token_quota(self, identity: Identity) -> tuple[bool, str]:  # noqa: ARG002
        return True, ""

    def record_chat_turn(self, identity: Identity) -> int:  # noqa: ARG002
        return 0

    def record_chat_tokens(  # noqa: D401
        self,
        identity: Identity,  # noqa: ARG002
        prompt_tokens: int,  # noqa: ARG002
        completion_tokens: int,  # noqa: ARG002
        *,
        model: str = "unknown",  # noqa: ARG002
        kind: str = "chat",  # noqa: ARG002
    ) -> None:
        return None

    def record_embed_tokens(
        self,
        identity: Identity,  # noqa: ARG002
        estimated_tokens: int,  # noqa: ARG002
        *,
        model: str = "unknown",  # noqa: ARG002
    ) -> None:
        return None

    def chat_quota_snapshot(self, identity: Identity) -> dict:  # noqa: ARG002
        return {}


class ZeroBillingHook:
    def estimate_usd_for_usage(
        self,
        model: str,  # noqa: ARG002
        prompt_tokens: int,  # noqa: ARG002
        completion_tokens: int,  # noqa: ARG002
    ) -> float:
        return 0.0


class PassThroughSessionScope:
    def qualify_session_id(self, identity: Identity, client_session_id: str | None) -> str:  # noqa: ARG002
        raw = (client_session_id or "default").strip() or "default"
        return raw

    def qualify_session_http(self, identity: Identity, client_session_id: str | None) -> str:
        try:
            return self.qualify_session_id(identity, client_session_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    def owner_user_from_session_id(self, session_id: str) -> str:  # noqa: ARG002
        return SINGLE_USER_ID

    def session_id_prefix_for_identity(self, identity: Identity) -> str | None:  # noqa: ARG002
        return None

    def ensure_session_owned_by_identity(self, identity: Identity, sid: str) -> None:  # noqa: ARG002
        return None

    def ensure_message_owned_by_identity(self, identity: Identity, message: dict) -> None:  # noqa: ARG002
        return None


_CHANNEL_SESSION_PREFIX = {"telegram": "tg", "discord": "dc", "line": "line"}


class SingleUserBridgeScope:
    """OSS bridge scope: the channel user is the only user. Sessions are
    ``<channel>_<id>`` over the shared chat connection; ``/link`` is a no-op."""

    def session_id(self, channel: str, channel_user_id: str) -> str:
        prefix = _CHANNEL_SESSION_PREFIX.get(channel, channel)
        return f"{prefix}_{channel_user_id}"

    def connection(self, channel: str, channel_user_id: str):  # noqa: ARG002
        from yumi.core.platform.security.connection import resolve_connection_config

        return resolve_connection_config("chat")

    def link(self, channel: str, channel_user_id: str, code: str) -> str:  # noqa: ARG002
        return "Single-user mode — no account binding needed; just send a message."


class SharedBotPool:
    """Always returns the singleton bot from :mod:`yumi.core.platform.runtime.accessors`."""

    async def get_bot_for_identity(self, identity: Identity) -> "YumiBot":  # noqa: ARG002
        from yumi.core.platform.runtime.accessors import get_bot

        return get_bot()

    async def get_bot_for_session_owner(self, owner_user_id: str) -> "YumiBot":  # noqa: ARG002
        from yumi.core.platform.runtime.accessors import get_bot

        return get_bot()

    def invalidate(self, user_id: str) -> None:  # noqa: ARG002
        return None

    def start_idle_sweep(self) -> None:
        return None


class SharedMemoryFactory:
    """Always returns the shared OSS LanceDB :class:`Memory`."""

    def get_for_identity(self, identity: Identity) -> "Memory":  # noqa: ARG002
        from yumi.core.features.memory.store import get_memory_store

        return get_memory_store()

    def get_for_session_owner(self, owner_user_id: str) -> "Memory":  # noqa: ARG002
        from yumi.core.features.memory.store import get_memory_store

        return get_memory_store()

    def assert_quota_for_session(self, session_id: str) -> None:  # noqa: ARG002
        return None

    def invalidate_size_cache(self, user_id: str) -> None:  # noqa: ARG002
        return None


class FlatEdgeScope:
    """OSS edge scope: no per-user prefix; all edges share the global namespace."""

    def connection_key(self, owner_user_id: str | None, edge_name: str) -> str:  # noqa: ARG002
        return edge_name

    def tool_register_prefix(self, owner_user_id: str | None, edge_name: str) -> str:  # noqa: ARG002
        # Reuse the one canonical provider-safe prefix builder (don't duplicate
        # the sanitizer — a stale copy here would emit provider-invalid names).
        from yumi.core.platform.runtime.edge_naming import edge_tool_key_prefix

        return edge_tool_key_prefix(edge_name)

    def filter_edge_tool_schemas(
        self,
        identity: Identity,  # noqa: ARG002
        registry: dict[str, dict],
        disabled: set[str],
    ) -> list:
        out: list = []
        for edge_tools in registry.values():
            for name, entry in edge_tools.items():
                if name not in disabled:
                    out.append(entry["schema"])
        return out

    def resolve_owner_user_id(self, auth_msg: dict) -> str | None:  # noqa: ARG002
        # Single-user / OSS: no server-side ownership resolution; the caller falls
        # back to the client-supplied owner_user_id.
        return None

    def on_edge_register(self, connection_key: str, auth_msg: dict) -> None:  # noqa: ARG002
        return None

    def on_edge_disconnect(self, connection_key: str) -> None:  # noqa: ARG002
        return None


class LoggingAuditSink:
    def event(self, event: str, user_id: str | None = None, **fields: object) -> None:
        _log.info("audit %s user_id=%s %s", event, user_id, fields)


class NoOpSystemPromptExtender:
    """OSS default — single-user deployments don't need extra prompt context."""

    def extra_system_prompt_sections(self, identity: Identity) -> list[str]:  # noqa: ARG002
        return []


class NoOpRouteExtender:
    def mount(self, app: "FastAPI") -> None:  # noqa: ARG002
        return None


class NoOpMiddlewareExtender:
    def middlewares(self) -> list:
        return []


class NoOpAdminCli:
    def add_arguments(self, parser: Any) -> None:  # noqa: ARG002
        return None

    def handle(self, args: Any) -> bool:  # noqa: ARG002
        return False
