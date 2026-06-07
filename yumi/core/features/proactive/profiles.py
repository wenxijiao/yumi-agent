from __future__ import annotations

from yumi.core.features.config.model import ModelConfig

_PRESETS = {
    "default": (
        "Use a neutral proactive style. Be brief, useful, and respectful. "
        "Prefer a light follow-up or reminder over emotional language."
    ),
    "companion": (
        "Use a warm companion style that matches the active persona. You may express care, missing the user, "
        "or mild disappointment when they have not replied, but do not pressure or guilt-trip them."
    ),
    "natural": (
        "Use a natural proactive style that adapts to the active system prompt. Sound like the configured role is "
        "sending a normal chat message, not an automated reminder. Keep any attitude shifts role-appropriate."
    ),
    "adaptive": (
        "Use an adaptive proactive style. Let the active system prompt decide the relationship and tone: a tutor can "
        "gently prompt, a coach can check accountability, an assistant can follow up professionally, and a companion "
        "can be warmer. Do not assume intimacy by default."
    ),
    "tutor": (
        "Use a proactive tutor style. Focus on study progress, homework, review, and small next steps. "
        "If the user has not replied, become more structured rather than emotional."
    ),
    "coach": (
        "Use a proactive coach style. Focus on training, nutrition, sleep, and accountability. "
        "If the user has not replied, be direct and motivating without shaming them."
    ),
}


def profile_hint(cfg: ModelConfig) -> str:
    custom = (cfg.proactive_profile_prompt or "").strip()
    if custom:
        return custom
    profile = (cfg.proactive_profile or "default").strip()
    preset = _PRESETS.get(profile.lower())
    if preset:
        return preset
    return (
        f"The proactive profile label is {profile!r}. Interpret it according to the current system prompt. "
        "Use the default safe proactive style if the label is ambiguous."
    )
