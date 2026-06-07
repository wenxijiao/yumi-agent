from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from kumi.core.features.config.model import ModelConfig
from kumi.core.features.proactive.state import ProactiveSessionState

SmartInteractionState = Literal["casual", "waiting", "light_nudge", "reserved", "give_space"]


@dataclass(frozen=True)
class SmartInteraction:
    state: SmartInteractionState
    max_messages: int
    style_guidance: str


def smart_interaction_state(state: ProactiveSessionState) -> SmartInteractionState:
    count = max(0, int(state.unreplied_count or 0))
    if count <= 0:
        return "casual"
    if count == 1:
        return "waiting"
    if count == 2:
        return "light_nudge"
    if count == 3:
        return "reserved"
    return "give_space"


def smart_followup_delay_multiplier(state: ProactiveSessionState) -> float:
    """Slow unreplied follow-ups down as the user keeps not replying."""
    current = smart_interaction_state(state)
    if current == "waiting":
        return 1.0
    if current == "light_nudge":
        return 1.75
    if current == "reserved":
        return 3.0
    if current == "give_space":
        return 6.0
    return 1.0


def should_give_space(cfg: ModelConfig, state: ProactiveSessionState) -> bool:
    limit = max(1, int(cfg.proactive_smart_max_unreplied_followups))
    return int(state.unreplied_count or 0) >= limit


def smart_interaction(cfg: ModelConfig, state: ProactiveSessionState, *, trigger: str | None) -> SmartInteraction:
    current = smart_interaction_state(state)
    intensity = (cfg.proactive_smart_naturalness or "balanced").strip().lower()
    if intensity == "off":
        return SmartInteraction(
            state="casual",
            max_messages=3,
            style_guidance=(
                "Use the existing proactive behavior. Stay brief, useful, and aligned with the active system prompt."
            ),
        )

    base = (
        "Follow the active system prompt exactly. Do not assume a romantic or companion role unless the system prompt "
        "already establishes one. Make the message feel like a natural chat turn from that role, not a notification."
    )
    natural = (
        " Prefer short, imperfect chat phrasing over polished summaries. It is okay to leave the thought slightly open "
        "instead of ending with a service-like reassurance."
    )
    if intensity == "subtle":
        natural = " Keep the naturalness subtle: concise, not scripted, and still practical."

    if current == "casual":
        return SmartInteraction(
            state=current,
            max_messages=2,
            style_guidance=(
                f"{base}{natural} This is a casual smart check-in. Mention one specific, timely thought if useful; "
                "do not ask a question every time."
            ),
        )
    if current == "waiting":
        return SmartInteraction(
            state=current,
            max_messages=2,
            style_guidance=(
                f"{base}{natural} The user has not replied to the previous proactive message. Send a light follow-up "
                "that acknowledges the pause without pressure."
            ),
        )
    if current == "light_nudge":
        return SmartInteraction(
            state=current,
            max_messages=2,
            style_guidance=(
                f"{base}{natural} The user still has not replied. A small shift in attitude is allowed, but express it "
                "in a role-appropriate way: a partner may sound a little hurt, a teacher may gently prompt, a coach may "
                "check accountability, and an assistant or employee should stay polite and professional. Do not guilt-trip."
            ),
        )
    if current == "reserved":
        return SmartInteraction(
            state=current,
            max_messages=1,
            style_guidance=(
                f"{base}{natural} The user has ignored several proactive messages. Be more reserved and brief. Avoid "
                "another demanding question; if the active role supports emotion, keep it mild and controlled."
            ),
        )
    return SmartInteraction(
        state=current,
        max_messages=1,
        style_guidance=(
            f"{base} The user has not replied after several proactive messages. Usually output <skip/> and give them "
            "space. Only send one very short message if the context is genuinely important."
        ),
    )
