"""Default single-user implementations of every plugin port.

These ship with OSS so the codebase has zero behavioural dependency on
commercial extensions. ``kumi-enterprise`` overrides each port via
:func:`kumi.core.platform.plugins.register_plugin` at import time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import HTTPException
from kumi.core.platform.plugins.identity import LOCAL_IDENTITY, SINGLE_USER_ID, Identity, context_identity
from kumi.logging_config import get_logger

if TYPE_CHECKING:
    from fastapi import FastAPI
    from kumi.core.chatbot import KumiBot
    from kumi.core.features.memory.memory import Memory

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


class SharedBotPool:
    """Always returns the singleton bot from :mod:`kumi.core.api.state`."""

    async def get_bot_for_identity(self, identity: Identity) -> "KumiBot":  # noqa: ARG002
        from kumi.core.api.state import get_bot

        return get_bot()

    async def get_bot_for_session_owner(self, owner_user_id: str) -> "KumiBot":  # noqa: ARG002
        from kumi.core.api.state import get_bot

        return get_bot()

    def invalidate(self, user_id: str) -> None:  # noqa: ARG002
        return None

    def start_idle_sweep(self) -> None:
        return None


class SharedMemoryFactory:
    """Always returns the shared OSS LanceDB :class:`Memory`."""

    def get_for_identity(self, identity: Identity) -> "Memory":  # noqa: ARG002
        from kumi.core.api.state import get_memory_store

        return get_memory_store()

    def get_for_session_owner(self, owner_user_id: str) -> "Memory":  # noqa: ARG002
        from kumi.core.api.state import get_memory_store

        return get_memory_store()

    def assert_quota_for_session(self, session_id: str) -> None:  # noqa: ARG002
        return None

    def invalidate_size_cache(self, user_id: str) -> None:  # noqa: ARG002
        return None


def _gemini_safe_segment(value: str) -> str:
    import re

    s = (value or "").strip()
    if not s:
        return "edge"
    t = re.sub(r"[^a-zA-Z0-9_.:-]+", "_", s)
    t = re.sub(r"_+", "_", t).strip("_")
    if not t:
        return "edge"
    if t[0] in "0123456789.-:":
        t = "e" + t
    return t[:80]


class FlatEdgeScope:
    """OSS edge scope: no per-user prefix; all edges share the global namespace."""

    def connection_key(self, owner_user_id: str | None, edge_name: str) -> str:  # noqa: ARG002
        return edge_name

    def tool_register_prefix(self, owner_user_id: str | None, edge_name: str) -> str:  # noqa: ARG002
        return f"edge_{_gemini_safe_segment(edge_name)}__"

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
