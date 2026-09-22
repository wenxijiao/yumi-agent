"""Build LLM message lists: system extras, upload nudges, optional image inlining."""

from __future__ import annotations

import base64
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from yumi.core.features.prompts.catalog import (
    CURRENT_TIME_TEMPLATE,
    NO_VISION_IMAGE_UPLOAD_INSTRUCTION,
    UPLOAD_FILE_INSTRUCTION,
    build_tool_use_instruction,
)
from yumi.core.platform.runtime.assistant_context import PromptSnapshot
from yumi.core.platform.runtime.caller_context import get_chat_owner_user_id
from yumi.core.platform.storage.upload_paths import resolve_owned_image
from yumi.core.platform.timezone import format_user_facing_time

if TYPE_CHECKING:
    from yumi.core.features.config import ModelConfig
    from yumi.core.features.memory.memory import Memory

# Extra nudge when the user message clearly references Yumi upload storage.
_UPLOAD_PATH_RE = re.compile(r"\.yumi[/\\]+uploads[/\\]", re.IGNORECASE)

# Channel session-id prefixes; used to compute peer sessions for cross-channel
# context (voice <-> telegram <-> discord <-> line <-> chat). Order is intentional: it determines the
# label fallback when a session_id matches multiple prefixes.
_CHANNEL_PREFIXES = ("voice_", "tg_", "dc_", "line_", "chat_")


def _peer_session_ids(session_id: str) -> list[str]:
    """Sibling session ids for the same owner across other channels.

    Voice/telegram/discord/line/chat sessions are named ``<channel>_<owner>``; given one
    of them, return the other channels. Sessions that don't follow this scheme
    return ``[]`` (unchanged behaviour for legacy ids like ``chat_<uuid>``).
    """
    for prefix in _CHANNEL_PREFIXES:
        if session_id.startswith(prefix):
            owner = session_id[len(prefix) :]
            if not owner:
                return []
            return [p + owner for p in _CHANNEL_PREFIXES if (p + owner) != session_id]
    return []


_UPLOAD_ANY_PATH_RE = re.compile(r"(/[^\s\n]+?\.yumi/uploads/[^\s\n]+)", re.IGNORECASE)

_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif", ".ico"})
_MIME_MAP = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".ico": "image/x-icon",
}
_MAX_INLINE_IMAGE_BYTES = 4 * 1024 * 1024
_MAX_INLINE_IMAGES_TOTAL_BYTES = 8 * 1024 * 1024

_UPLOAD_IMAGE_PATH_RE = re.compile(
    r"(/[^\s\n]+?\.yumi/uploads/[^\s\n]+\.(?:png|jpg|jpeg|gif|webp|bmp|tiff|tif|ico))",
    re.IGNORECASE,
)

_UPLOADS_ROOT: Path | None = None


def _get_uploads_root() -> Path:
    global _UPLOADS_ROOT
    if _UPLOADS_ROOT is None:
        _UPLOADS_ROOT = (Path.home() / ".yumi" / "uploads").resolve()
    return _UPLOADS_ROOT


def _prompt_has_non_image_upload_paths(prompt: str) -> bool:
    """True if ``prompt`` references an upload path whose extension is not a known image type."""
    for m in _UPLOAD_ANY_PATH_RE.finditer(prompt):
        p = m.group(1).strip()
        ext = Path(p).suffix.lower()
        if not ext:
            return True
        if ext not in _IMAGE_EXTENSIONS:
            return True
    return False


def _inline_uploaded_images(messages: list[dict], *, vision_supported: bool = True) -> list[dict]:
    """Scan user messages for uploaded image paths."""
    uploads_root = _get_uploads_root()
    result: list[dict] = []
    for msg in messages:
        if msg.get("role") != "user" or not isinstance(msg.get("content"), str):
            result.append(msg)
            continue

        content = msg["content"]
        image_paths = _UPLOAD_IMAGE_PATH_RE.findall(content)
        if not image_paths:
            result.append(msg)
            continue

        valid_images: list[tuple[str, str, str]] = []
        total_bytes = 0
        for path_str in image_paths:
            try:
                p = resolve_owned_image(path_str, get_chat_owner_user_id(), root=uploads_root)
                size = p.stat().st_size
                if size > _MAX_INLINE_IMAGE_BYTES:
                    continue
                if total_bytes + size > _MAX_INLINE_IMAGES_TOTAL_BYTES:
                    # Skip remaining images for this turn rather than blowing the model context.
                    continue
                ext = p.suffix.lower()
                if ext not in _IMAGE_EXTENSIONS:
                    continue
                data = p.read_bytes()
                b64 = base64.standard_b64encode(data).decode("ascii")
                mime = _MIME_MAP.get(ext, "image/png")
                valid_images.append((path_str, b64, mime))
                total_bytes += size
            except Exception:
                continue

        if not valid_images:
            result.append(msg)
            continue

        text = content
        for path_str, _, _ in valid_images:
            text = text.replace(path_str, f"[image: {Path(path_str).name}]")
        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        if not vision_supported:
            result.append({**msg, "content": text})
            continue

        parts: list[dict] = [{"type": "text", "text": text}]
        for _, b64, mime in valid_images:
            parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})

        result.append({**msg, "content": parts})
    return result


def messages_have_multimodal_images(messages: list[dict]) -> bool:
    """True if any user message uses OpenAI-style multimodal parts with ``image_url``."""
    for msg in messages:
        c = msg.get("content")
        if not isinstance(c, list):
            continue
        for part in c:
            if isinstance(part, dict) and part.get("type") == "image_url":
                return True
    return False


def _add_ephemeral_messages(messages: list[dict], ephemeral_messages: list | None) -> None:
    """Append ephemeral messages at the tail.

    Per-turn system notes (runtime context, language hints, retry nudges) go
    AFTER the transcript, not into the leading system block: they change every
    turn, and anything placed before the history invalidates the provider
    prompt-cache prefix on every request. Non-system ephemeral messages
    (in-flight tool spans) keep conversation order and come first.
    """
    if not ephemeral_messages:
        return
    system_notes = [msg for msg in ephemeral_messages if isinstance(msg, dict) and msg.get("role") == "system"]
    system_note_ids = {id(msg) for msg in system_notes}
    other_messages = [msg for msg in ephemeral_messages if id(msg) not in system_note_ids]
    if other_messages:
        messages.extend(other_messages)
    if system_notes:
        messages.extend(system_notes)


def compose_messages(
    memory: Memory,
    *,
    prompt: str | None,
    tools: list | None,
    ephemeral_messages: list | None,
    cfg: ModelConfig,
    upload_mode: Literal["vision", "no_vision"],
    exclude_message_ids: set[str] | None = None,
    prompt_snapshot: PromptSnapshot | None = None,
    response_language: str | None = None,
) -> list[dict]:
    """Build messages with system extras and optional image inlining (vision vs text-only).

    Layout is cache-aware: the leading system block carries only content that
    is stable across turns (base prompt + tool policy). Anything that changes
    per turn — current time, upload nudges, runtime context — is appended as
    tail system notes AFTER the transcript, so the provider prompt-cache
    prefix (tools → system → history) stays byte-identical between requests.
    """
    stamp = memory.redaction_stamp() if hasattr(memory, "redaction_stamp") else ""
    if prompt_snapshot is not None and prompt_snapshot.messages is not None:
        if stamp != prompt_snapshot.redaction_stamp:
            raise ValueError("Saved context changed during this request. Please send again.")
        messages = deepcopy(prompt_snapshot.messages + prompt_snapshot.tool_messages)
        extra = [m for m in (ephemeral_messages or []) if id(m) not in prompt_snapshot.initial_note_ids]
        _add_ephemeral_messages(messages, extra)
        if upload_mode == "no_vision" and any(
            m.get("role") == "user" and _UPLOAD_IMAGE_PATH_RE.search(str(m.get("content") or "")) for m in messages
        ):
            messages.append({"role": "system", "content": NO_VISION_IMAGE_UPLOAD_INSTRUCTION.strip()})
        return _inline_uploaded_images(messages, vision_supported=upload_mode == "vision")
    peers = _peer_session_ids(memory.session_id)
    messages = memory.get_context(query=prompt, peer_session_ids=peers, exclude_message_ids=exclude_message_ids)
    if messages and messages[0].get("role") == "system":
        # Stable head extras only. The tool policy text no longer enumerates
        # tool names, so it is byte-identical across turns for a deployment.
        if tools and cfg.chat_append_tool_use_instruction:
            messages[0] = {
                "role": "system",
                "content": messages[0]["content"] + build_tool_use_instruction(tools),
            }

    tail_notes: list[str] = []
    if cfg.chat_append_current_time:
        line = format_user_facing_time(datetime.now(timezone.utc), cfg.local_timezone)
        tail_notes.append(CURRENT_TIME_TEMPLATE.format(time=line))
    if tools and prompt and _UPLOAD_PATH_RE.search(prompt):
        if upload_mode == "vision":
            tail_notes.append(UPLOAD_FILE_INSTRUCTION.strip())
        else:
            if _prompt_has_non_image_upload_paths(prompt):
                tail_notes.append(UPLOAD_FILE_INSTRUCTION.strip())
            if _UPLOAD_IMAGE_PATH_RE.search(prompt):
                tail_notes.append(NO_VISION_IMAGE_UPLOAD_INSTRUCTION.strip())

    _add_ephemeral_messages(messages, ephemeral_messages)
    for note in tail_notes:
        messages.append({"role": "system", "content": note})
    if prompt:
        from yumi.core.features.chat.language import language_scoped_prompt

        content = language_scoped_prompt(prompt, response_language) if response_language is not None else prompt
        messages.append({"role": "user", "content": content})

    if prompt_snapshot is not None:
        prompt_snapshot.messages = deepcopy(messages)
        prompt_snapshot.initial_note_ids = {id(m) for m in (ephemeral_messages or [])}
        prompt_snapshot.redaction_stamp = stamp

    return _inline_uploaded_images(
        messages,
        vision_supported=(upload_mode == "vision"),
    )
