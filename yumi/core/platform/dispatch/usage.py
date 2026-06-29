"""Token accounting for one chat turn.

A context manager that absorbs ``usage`` chunks from the provider stream and,
on exit, hands the totals to the tool-routing recorder and the quota policy.
The orchestrator never touches token integers directly.
"""

from __future__ import annotations

from typing import Any

from yumi.core.platform.dispatch.context import TurnContext
from yumi.core.platform.plugins import SINGLE_USER_ID, get_current_identity, get_quota_policy
from yumi.core.platform.tools.routing import record_tool_routing_usage
from yumi.logging_config import get_logger

logger = get_logger(__name__)


class UsageRecorder:
    """Accumulates token totals during a turn and persists them on exit."""

    def __init__(self, ctx: TurnContext, *, bot: Any | None = None, owner_uid: str | None = None) -> None:
        self.ctx = ctx
        self.bot = bot
        self.owner_uid = owner_uid
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.usage_model = ""

    def add(self, chunk: dict) -> None:
        self.total_prompt_tokens += int(chunk.get("prompt_tokens", 0) or 0)
        self.total_completion_tokens += int(chunk.get("completion_tokens", 0) or 0)
        if chunk.get("model"):
            self.usage_model = str(chunk["model"])

    def __enter__(self) -> "UsageRecorder":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        model = self.usage_model or (self.bot.model_name if self.bot is not None else "")
        try:
            record_tool_routing_usage(
                session_id=self.ctx.session_id,
                prompt_tokens=self.total_prompt_tokens,
                completion_tokens=self.total_completion_tokens,
                model=model,
            )
            if self.bot is not None:
                ident = get_current_identity()
                if ident.user_id != SINGLE_USER_ID and ident.user_id == self.owner_uid:
                    get_quota_policy().record_chat_tokens(
                        ident,
                        self.total_prompt_tokens,
                        self.total_completion_tokens,
                        model=self.usage_model or self.bot.model_name,
                    )
        except Exception:
            logger.debug("record_chat_tokens skipped", exc_info=True)

        # Persist per-turn token usage to SQLite so the stats dashboard survives
        # restarts (the routing recorder above is in-memory only). Isolated in its
        # own guard so a storage hiccup never affects the turn or quota accounting.
        if self.total_prompt_tokens or self.total_completion_tokens:
            try:
                _persist_token_usage(
                    session_id=self.ctx.session_id,
                    owner_user_id=self.owner_uid or "",
                    model=model,
                    prompt_tokens=self.total_prompt_tokens,
                    completion_tokens=self.total_completion_tokens,
                )
            except Exception:
                logger.debug("token usage persistence skipped", exc_info=True)


def _persist_token_usage(
    *,
    session_id: str,
    owner_user_id: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
    """Write one ``token_usage`` row to the default memory store (best effort).

    Deliberately avoids ``load_model_config()`` (which runs ~7 SQLite SELECTs)
    on the hot per-turn path; the stats dashboard groups by ``model``, not
    ``provider``, so the provider column is left blank.
    """
    from yumi.core.features.memory.store import get_memory_store

    get_memory_store().sqlite.record_token_usage(
        session_id=session_id,
        owner_user_id=owner_user_id,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
