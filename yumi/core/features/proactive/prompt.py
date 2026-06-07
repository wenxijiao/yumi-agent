from __future__ import annotations

import re
from datetime import datetime, timezone

from yumi.core.features.config.model import ModelConfig
from yumi.core.features.proactive.interaction import smart_interaction
from yumi.core.features.proactive.planner import ProactiveDecision
from yumi.core.features.proactive.profiles import profile_hint
from yumi.core.features.proactive.state import ProactiveSessionState
from yumi.core.features.proactive.timezone_utils import format_user_facing_time

_MSG_RE = re.compile(r"<msg>(.*?)</msg>", re.DOTALL | re.IGNORECASE)


def build_proactive_prompt(
    cfg: ModelConfig,
    state: ProactiveSessionState,
    decision: ProactiveDecision,
    *,
    now: datetime,
    context_lines: list[str] | None = None,
) -> str:
    now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    current_time = f"Current time: {format_user_facing_time(now_utc, cfg.local_timezone)}"
    context_items = [current_time, *[line for line in (context_lines or []) if line.strip()]]
    context = "\n".join(f"- {line}" for line in context_items)
    context_block = f"\n[Proactive Context]\n{context}\n"
    style_block = ""
    if (cfg.proactive_mode or "").strip().lower() == "smart":
        interaction = smart_interaction(cfg, state, trigger=decision.trigger)
        style_block = (
            "\n[Smart Proactive Style]\n"
            f"- Interaction state: {interaction.state}\n"
            f"- Maximum chat bubbles: {interaction.max_messages}\n"
            f"- Guidance: {interaction.style_guidance}\n"
        )
    return (
        "[Proactive message request]\n"
        "Generate a short proactive outbound message for this session.\n"
        "Follow the active system prompt and session persona. Do not invent a different role.\n"
        f"Profile guidance: {profile_hint(cfg)}\n"
        f"Tone intensity: {cfg.proactive_tone_intensity}\n"
        f"Trigger: {decision.trigger or 'check_in'} ({decision.reason})\n"
        f"Unreplied proactive count: {state.unreplied_count}\n"
        f"{context_block}"
        f"{style_block}"
        "Rules:\n"
        "- Output only the message text, or <skip/> if now is not a good time.\n"
        "- Keep it natural for the configured persona and use the user's likely language.\n"
        "- Prefer 1-3 short chat messages using <msg>...</msg> blocks when multiple bubbles feel natural.\n"
        "- Respect the Smart Proactive Style maximum chat bubbles when it is present.\n"
        "- Do not mention this scheduler, configuration, or background job.\n"
        "- Do not claim you used tools unless the context explicitly contains that information.\n"
    )


_TELEGRAM_PER_PART_LIMIT = 4000


def _clamp(part: str) -> str:
    """Trim each part to Telegram's safe per-message size to avoid 400 errors."""
    if len(part) <= _TELEGRAM_PER_PART_LIMIT:
        return part
    return part[: _TELEGRAM_PER_PART_LIMIT - 3] + "..."


def split_proactive_messages(text: str, *, max_parts: int = 3) -> list[str]:
    raw = (text or "").strip()
    if not raw or raw.lower() == "<skip/>":
        return []
    tagged = [m.group(1).strip() for m in _MSG_RE.finditer(raw) if m.group(1).strip()]
    if tagged:
        return [_clamp(p) for p in tagged[:max_parts]]
    chunks = [p.strip() for p in re.split(r"\n\s*\n+", raw) if p.strip()]
    if len(chunks) > 1:
        return [_clamp(p) for p in chunks[:max_parts]]
    return [_clamp(raw)]
