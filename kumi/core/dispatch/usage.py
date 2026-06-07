"""Token accounting for one chat turn.

A context manager that absorbs ``usage`` chunks from the provider stream and,
on exit, hands the totals to the tool-routing recorder and the quota policy.
The orchestrator never touches token integers directly.
"""

from __future__ import annotations

from typing import Any

from kumi.core.dispatch.context import TurnContext
from kumi.core.plugins import SINGLE_USER_ID, get_current_identity, get_quota_policy
from kumi.core.tool_routing import record_tool_routing_usage
from kumi.logging_config import get_logger

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
        try:
            record_tool_routing_usage(
                session_id=self.ctx.session_id,
                prompt_tokens=self.total_prompt_tokens,
                completion_tokens=self.total_completion_tokens,
                model=self.usage_model or (self.bot.model_name if self.bot is not None else ""),
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
