"""Per-chat 'reply with voice?' toggle for messaging bridges.

In-memory and per-process: each bridge process tracks the chats that asked for
spoken replies (via ``/voice on`` on Telegram, ``!voice on`` on Discord). State
resets when the bridge restarts — a deliberate, simple v1.
"""

from __future__ import annotations

_voice_chats: set[str] = set()


def _key(channel: str, chat_id: object) -> str:
    return f"{channel}:{chat_id}"


def set_voice_reply(channel: str, chat_id: object, enabled: bool) -> None:
    key = _key(channel, chat_id)
    if enabled:
        _voice_chats.add(key)
    else:
        _voice_chats.discard(key)


def is_voice_reply(channel: str, chat_id: object) -> bool:
    return _key(channel, chat_id) in _voice_chats
