"""Canonical user-facing copy shared by the chat bridges (Telegram / Discord / LINE).

One help text and one unlinked-guidance string so every channel presents the
same interface. Power/debug commands (/model, /system, /start_log, /end_log)
keep working on every bridge but are deliberately not listed for end users.
"""


def bridge_help_text(*, voice: bool = True, timers: bool = True) -> str:
    """The /help reply. Flags drop commands a channel doesn't support yet."""
    lines = [
        "Hi, I'm Yumi 👋",
        "",
        "Just talk to me in plain words — I can save memos and notes, quiz you "
        "on what you're learning, set reminders, and more. Photos, files, and "
        "voice messages work too.",
        "",
        "New here? Connect your account first:",
        "/link <code> — your code is in the Yumi app, under Settings → Yumi",
        "",
        "Handy commands:",
        "/clear — start a fresh conversation",
    ]
    if voice:
        lines.append("/voice on|off — voice replies on or off")
    if timers:
        lines.append("/timers — see your reminders")
        lines.append("/cancel_timer <id> — cancel a reminder")
    lines.append("/help — show this message")
    return "\n".join(lines)


BRIDGE_UNLINKED_TEXT = (
    "This account isn't linked to Yumi yet. Send /link followed by the "
    "connection code from your Yumi app (Settings → Yumi) to connect."
)
