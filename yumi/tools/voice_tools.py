"""A conversation control, scoped to a capable, active voice client."""

from yumi.core.platform.runtime.assistant_context import message_media


def end_voice_conversation() -> dict:
    if not (message_media.get() or {}).get("voice_session_controls"):
        return {"ok": False, "error": "No active voice session supports standby."}
    return {"ok": True, "voice_state": "standby"}
