"""Telegram client for Yumi: forwards messages to POST /chat (NDJSON) and handles tool confirmations."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from fastapi import HTTPException

from yumi.core.features.config import get_telegram_allowed_user_ids, get_telegram_bot_token
from yumi.core.features.proactive import record_user_message
from yumi.core.features.prompts.http_bridge import (
    format_effective_prompt_reply,
    http_delete_session_prompt,
    http_get_global_system_prompt,
    http_get_session_prompt,
    http_put_session_prompt,
)
from yumi.core.features.uploads.service import MAX_UPLOAD_BYTES, save_uploaded_file
from yumi.core.platform.http.events import ErrorEvent, TextEvent, ToolConfirmationEvent, parse_chat_event
from yumi.core.platform.http.stream_consumer import BaseChannelHandler, consume_chat_stream
from yumi.core.platform.security.connection import ConnectionConfig
from yumi.logging_config import get_logger
from yumi.telegram.bridge import chat_connection_config

# Pending tool confirmations: short_id -> Future[str] with values deny|allow|always
_PENDING_TOOL_CONFIRM: dict[str, asyncio.Future[str]] = {}

_MAX_MSG_LEN = 4096
_LOG = get_logger(__name__)


def _truncate_for_telegram(text: str, max_chars: int = 4090) -> str:
    """Telegram rejects ``send_message`` / ``reply_text`` when ``text`` length exceeds 4096."""
    s = text if isinstance(text, str) else str(text)
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1] + "…"


def _api_url(connection: ConnectionConfig, path: str) -> str:
    return f"{connection.base_url.rstrip('/')}{path}"


def _chat_url(connection: ConnectionConfig) -> str:
    return f"{connection.base_url.rstrip('/')}/chat"


def _session_id_for_user(telegram_user_id: int) -> str:
    from yumi.core.platform.plugins import get_bridge_scope

    return get_bridge_scope().session_id("telegram", str(telegram_user_id))


def _split_telegram_text(text: str) -> list[str]:
    if len(text) <= _MAX_MSG_LEN:
        return [text]
    chunks: list[str] = []
    rest = text
    while rest:
        chunks.append(rest[:_MAX_MSG_LEN])
        rest = rest[_MAX_MSG_LEN:]
    return chunks


async def _send_long_text(send: Callable[[str], Awaitable[Any]], text: str) -> None:
    for chunk in _split_telegram_text(text):
        await send(chunk)


async def _send_voice_reply(context, chat_id: int, text: str) -> bool:
    """Synthesize *text* and send it as an audio message. Returns False on any
    failure so the caller can fall back to plain text."""
    import io

    try:
        from yumi.core.features.tts.playback import synthesize_with_fallback
        from yumi.core.features.tts.voice_message import to_ogg_opus_voice

        audio = await synthesize_with_fallback(text)
        voice = to_ogg_opus_voice(audio)
        buffer = io.BytesIO(voice.data)
        buffer.name = "reply.ogg"
        await context.bot.send_voice(
            chat_id=chat_id,
            voice=buffer,
            duration=max(1, int(round(voice.duration_secs))),
        )
        return True
    except Exception as exc:  # synthesis or upload failed
        _LOG.warning("telegram: voice reply failed, falling back to text: %s", exc)
        return False


async def _iter_chat_events_from_http_stream(response: httpx.Response):
    """Parse one HTTP NDJSON ``response`` body into typed :class:`ChatEvent` objects.

    Mirrors the legacy hand-rolled byte loop: decode chunks as UTF-8, split on
    ``\\n``, drop blank lines, validate each via :func:`parse_chat_event`.
    Validation errors are silently skipped so a malformed line never wedges
    the consumer (matches legacy ``json.JSONDecodeError`` behaviour).
    """
    from pydantic import ValidationError

    buffer = ""
    async for chunk in response.aiter_bytes():
        if not chunk:
            continue
        buffer += chunk.decode("utf-8", errors="replace")
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                yield parse_chat_event(line)
            except ValidationError:
                continue
            except json.JSONDecodeError:
                continue


async def _post_tool_confirm(connection: ConnectionConfig, call_id: str, decision: str) -> tuple[bool, str]:
    url = _api_url(connection, "/tools/confirm")
    headers = connection.auth_headers()
    headers["Content-Type"] = "application/json"
    timeout = httpx.Timeout(10.0, read=300.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, json={"call_id": call_id, "decision": decision}, headers=headers)
        if r.status_code >= 400:
            return False, r.text[:500]
        return True, ""


class _TelegramChatHandler(BaseChannelHandler):
    """Telegram-flavoured rendering for one ``/chat`` turn.

    * ``text`` chunks accumulate into ``self.text_parts`` and are sent in one
      ``send_long_text`` call after the stream ends.
    * ``tool_confirmation`` posts a Telegram inline-keyboard prompt and waits
      for the user's tap (resolved via :data:`_PENDING_TOOL_CONFIRM`).
    * ``error`` sends a single message containing the error content.
    * ``thought`` / ``tool_status`` are dropped — Telegram has no good UI for them.
    """

    CONFIRMATION_TIMEOUT_SECONDS = 600.0
    _DECISION_MAP = {"deny": "deny", "allow": "allow", "always": "always_allow"}

    def __init__(self, *, context, chat_id: int, connection: ConnectionConfig) -> None:
        self.context = context
        self.chat_id = chat_id
        self.connection = connection
        self.text_parts: list[str] = []

    async def on_text(self, event: TextEvent) -> None:
        self.text_parts.append(event.content)

    async def on_tool_confirmation(self, event: ToolConfirmationEvent) -> None:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        short_id = uuid.uuid4().hex
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        _PENDING_TOOL_CONFIRM[short_id] = future
        args_preview = json.dumps(event.arguments, ensure_ascii=False)[:800]
        text = _truncate_for_telegram(
            f"Tool confirmation required\n\nTool: {event.tool_name}\nArguments: {args_preview}"
        )
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Deny", callback_data=f"tc|{short_id}|deny"),
                    InlineKeyboardButton("Allow", callback_data=f"tc|{short_id}|allow"),
                ],
                [InlineKeyboardButton("Always allow", callback_data=f"tc|{short_id}|always")],
            ]
        )
        await self.context.bot.send_message(chat_id=self.chat_id, text=text, reply_markup=keyboard)
        try:
            action = await asyncio.wait_for(future, timeout=self.CONFIRMATION_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            await self.context.bot.send_message(chat_id=self.chat_id, text="Confirmation timed out.")
            action = "deny"
        finally:
            _PENDING_TOOL_CONFIRM.pop(short_id, None)
        decision = self._DECISION_MAP.get(action, "deny")
        ok, err = await _post_tool_confirm(self.connection, event.call_id, decision)
        if not ok:
            await self.context.bot.send_message(
                chat_id=self.chat_id,
                text=_truncate_for_telegram(f"Confirm failed: {err}"),
            )

    async def on_error(self, event: ErrorEvent) -> None:
        await self.context.bot.send_message(
            chat_id=self.chat_id,
            text=_truncate_for_telegram(f"Error: {event.content}"),
        )

    def final_text(self) -> str:
        return "".join(self.text_parts)


async def _post_clear_session(connection: ConnectionConfig, session_id: str) -> tuple[bool, str]:
    url = _api_url(connection, f"/clear?session_id={session_id}")
    headers = connection.auth_headers()
    timeout = httpx.Timeout(10.0, read=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, headers=headers)
        if r.status_code >= 400:
            return False, r.text[:500]
        return True, ""


async def _put_chat_debug(
    connection: ConnectionConfig, session_id: str, enabled: bool
) -> tuple[bool, str, dict | None]:
    url = _api_url(connection, "/config/chat-debug")
    headers = connection.auth_headers()
    headers["Content-Type"] = "application/json"
    timeout = httpx.Timeout(10.0, read=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.put(url, json={"session_id": session_id, "enabled": enabled}, headers=headers)
        if r.status_code >= 400:
            return False, r.text[:500], None
        try:
            return True, "", r.json()
        except Exception:
            return True, "", None


async def _post_stt_transcribe(
    connection: ConnectionConfig,
    *,
    session_id: str,
    filename: str,
    data: bytes,
) -> tuple[bool, str]:
    url = _api_url(connection, "/stt/transcribe")
    headers = connection.auth_headers()
    headers["Content-Type"] = "application/json"
    payload = {
        "session_id": session_id,
        "filename": filename,
        "content_base64": base64.standard_b64encode(data).decode("ascii"),
    }
    timeout = httpx.Timeout(10.0, read=600.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(url, json=payload, headers=headers)
        if r.status_code >= 400:
            return False, r.text[:500]
        body = r.json()
        return True, str(body.get("text") or "").strip()


async def _get_model_config(connection: ConnectionConfig) -> dict[str, Any] | None:
    url = _api_url(connection, "/config/model")
    headers = connection.auth_headers()
    timeout = httpx.Timeout(10.0, read=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(url, headers=headers)
        if r.status_code >= 400:
            return None
        return r.json()


async def _get_timers(connection: ConnectionConfig) -> tuple[bool, str, list[dict[str, Any]]]:
    url = _api_url(connection, "/timers")
    headers = connection.auth_headers()
    timeout = httpx.Timeout(10.0, read=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(url, headers=headers)
        if r.status_code >= 400:
            return False, r.text[:500], []
        try:
            body = r.json()
        except Exception as exc:
            return False, str(exc), []
    timers = body.get("timers", [])
    return True, "", timers if isinstance(timers, list) else []


async def _delete_timer(connection: ConnectionConfig, timer_id: str) -> tuple[bool, str]:
    url = _api_url(connection, f"/timers/{timer_id}")
    headers = connection.auth_headers()
    timeout = httpx.Timeout(10.0, read=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.delete(url, headers=headers)
        if r.status_code >= 400:
            return False, r.text[:500]
        try:
            body = r.json()
        except Exception as exc:
            return False, str(exc)
    return body.get("status") == "success", str(body.get("message") or "")


def _format_timer_list_for_telegram(timers: list[dict[str, Any]]) -> str:
    if not timers:
        return "No active timers or scheduled tasks."

    lines = [f"Active timers ({len(timers)}):"]
    for timer in timers:
        timer_id = str(timer.get("id") or "?")
        kind = str(timer.get("type") or "timer")
        recurring = " recurring" if timer.get("recurring") else ""
        fire_at = str(timer.get("next_fire_at") or timer.get("fire_at") or "?")
        description = str(timer.get("description") or "")
        lines.append(f"{timer_id} — {kind}{recurring} — {fire_at}\n{description}")
    lines.append("\nCancel with /cancel_timer <id>")
    return "\n\n".join(lines)


def _authorized(user_id: int | None) -> bool:
    if user_id is None:
        return False
    allowed = get_telegram_allowed_user_ids()
    if not allowed:
        from yumi.core.platform.plugins import get_bridge_scope

        if type(get_bridge_scope()).__name__ != "SingleUserBridgeScope":
            return True
        return os.getenv("YUMI_BRIDGE_ALLOW_ALL", "").strip().lower() in {"1", "true", "yes"}
    return user_id in allowed


def build_application():
    """Build and return python-telegram-bot Application (v21+)."""
    try:
        from telegram.constants import ChatAction
        from telegram.ext import (
            Application,
            CallbackQueryHandler,
            CommandHandler,
            ContextTypes,
            MessageHandler,
            filters,
        )

        from telegram import (  # noqa: F401 — Inline* imports verify SDK availability
            InlineKeyboardButton,
            InlineKeyboardMarkup,
            Update,
        )
    except ImportError as exc:
        raise RuntimeError(
            "Failed to import python-telegram-bot (ships with yumi-agent). Reinstall: pip install --force-reinstall yumi-agent"
        ) from exc

    token = get_telegram_bot_token()
    if not token:
        raise RuntimeError(
            "Telegram bot token not set. Set TELEGRAM_BOT_TOKEN or add telegram_bot_token to ~/.yumi/config.json"
        )

    async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update.effective_user.id if update.effective_user else None):
            await update.message.reply_text("You are not authorized to use this bot.")
            return
        await update.message.reply_text(
            "Yumi Telegram bridge.\n\n"
            "Send a message to chat. You can attach photos, files, or voice/audio when STT is enabled.\n"
            "For one message: add a caption to the photo, or send text in a separate message.\n"
            "Commands:\n"
            "/voice on|off — reply with audio instead of text\n"
            "/clear — clear this chat's history\n"
            "/model — show server model config\n"
            "/system — view or change this chat's system prompt (not global)\n"
            "/timers — list active timers and scheduled tasks\n"
            "/cancel_timer <id> — cancel a timer or scheduled task\n"
            "/start_log — write full chat traces to ~/.yumi/debug/chat_trace/ (this session)\n"
            "/end_log — stop chat tracing\n"
            "/help — this message"
        )

    async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        await start_cmd(update, context)

    async def link_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        # /link binds this Telegram account when an identity plugin is present.
        # The single-user default just replies that no binding is needed.
        # Allowed even when not yet authorized.
        from yumi.core.platform.plugins import get_bridge_scope

        user = update.effective_user
        code = " ".join(context.args).strip() if context.args else ""
        reply = get_bridge_scope().link("telegram", str(user.id) if user else "", code)
        await update.message.reply_text(reply)

    async def voice_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update.effective_user.id if update.effective_user else None):
            await update.message.reply_text("You are not authorized to use this bot.")
            return
        from yumi.core.features.tts.reply_mode import is_voice_reply, set_voice_reply

        chat_id = update.effective_chat.id
        arg = context.args[0].strip().lower() if context.args else ""
        if arg in ("on", "off"):
            set_voice_reply("telegram", chat_id, arg == "on")
            await update.message.reply_text(
                "Voice replies are ON — I'll answer with audio." if arg == "on" else "Voice replies are OFF."
            )
            return
        state = "ON" if is_voice_reply("telegram", chat_id) else "OFF"
        await update.message.reply_text(f"Voice replies are {state}. Use /voice on or /voice off.")

    async def clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update.effective_user.id if update.effective_user else None):
            await update.message.reply_text("You are not authorized to use this bot.")
            return
        uid = update.effective_user.id
        session_id = _session_id_for_user(uid)
        connection = chat_connection_config(update.effective_user.id if update.effective_user else None)
        ok, err = await _post_clear_session(connection, session_id)
        if ok:
            await update.message.reply_text("Session cleared.")
        else:
            await update.message.reply_text(_truncate_for_telegram(f"Failed to clear: {err}"))

    async def start_log_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update.effective_user.id if update.effective_user else None):
            await update.message.reply_text("You are not authorized to use this bot.")
            return
        uid = update.effective_user.id
        session_id = _session_id_for_user(uid)
        connection = chat_connection_config(update.effective_user.id if update.effective_user else None)
        ok, err, data = await _put_chat_debug(connection, session_id, True)
        if not ok:
            await update.message.reply_text(_truncate_for_telegram(f"Failed to start debug log: {err}"))
            return
        path = (data or {}).get("trace_path") or ""
        await update.message.reply_text(
            _truncate_for_telegram(
                "Chat debug logging ON for this session.\n"
                f"Trace file: {path}\n"
                "Logs include turn boundaries, each full LLM request (messages + tools), and stream events.\n"
                "Optional: set YUMI_CHAT_DEBUG_REDACT_IMAGE_DATA=1 on the server to shorten inline data-URL images in the trace file only.\n"
                "Send /end_log to stop."
            )
        )

    async def end_log_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update.effective_user.id if update.effective_user else None):
            await update.message.reply_text("You are not authorized to use this bot.")
            return
        uid = update.effective_user.id
        session_id = _session_id_for_user(uid)
        connection = chat_connection_config(update.effective_user.id if update.effective_user else None)
        ok, err, data = await _put_chat_debug(connection, session_id, False)
        if not ok:
            await update.message.reply_text(_truncate_for_telegram(f"Failed to end debug log: {err}"))
            return
        path = (data or {}).get("trace_path") or ""
        if path:
            await update.message.reply_text(_truncate_for_telegram(f"Chat debug logging OFF. Last trace file:\n{path}"))
        else:
            await update.message.reply_text("Chat debug logging was not active for this session.")

    async def timers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update.effective_user.id if update.effective_user else None):
            await update.message.reply_text("You are not authorized to use this bot.")
            return
        connection = chat_connection_config(update.effective_user.id if update.effective_user else None)
        ok, err, timers = await _get_timers(connection)
        if not ok:
            await update.message.reply_text(_truncate_for_telegram(f"Failed to list timers: {err}"))
            return
        await _send_long_text(lambda t: update.message.reply_text(t), _format_timer_list_for_telegram(timers))

    async def cancel_timer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update.effective_user.id if update.effective_user else None):
            await update.message.reply_text("You are not authorized to use this bot.")
            return
        if not context.args or not str(context.args[0]).strip():
            await update.message.reply_text("Usage: /cancel_timer <timer_id>")
            return
        timer_id = str(context.args[0]).strip()
        connection = chat_connection_config(update.effective_user.id if update.effective_user else None)
        ok, message = await _delete_timer(connection, timer_id)
        if ok:
            await update.message.reply_text(_truncate_for_telegram(message or f"Cancelled {timer_id}."))
        else:
            await update.message.reply_text(_truncate_for_telegram(message or f"Failed to cancel {timer_id}."))

    async def model_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update.effective_user.id if update.effective_user else None):
            await update.message.reply_text("You are not authorized to use this bot.")
            return
        connection = chat_connection_config(update.effective_user.id if update.effective_user else None)
        cfg = await _get_model_config(connection)
        if not cfg:
            await update.message.reply_text("Could not read /config/model from the server.")
            return
        lines = [
            f"Chat: {cfg.get('chat_provider', '?')} / {cfg.get('chat_model', '?')}",
            f"Embedding: {cfg.get('embedding_provider', '?')} / {cfg.get('embedding_model', '?')}",
        ]
        await update.message.reply_text("\n".join(lines))

    def _system_help_text() -> str:
        return (
            "/system — Your personal prompt addendum (Telegram session)\n\n"
            "Your text is APPENDED to Yumi's built-in defaults and any per-app\n"
            "context, not used as a full replacement. Use it for personal\n"
            "preferences like 'always reply in English' or 'I'm a software engineer'.\n\n"
            "/system — or /system show — show the full composed prompt\n"
            "/system set <text> — set your addendum for this Telegram session\n"
            "/system reset — clear your addendum (defaults still apply)\n"
            "/system help — this help"
        )

    async def system_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _authorized(update.effective_user.id if update.effective_user else None):
            await update.message.reply_text("You are not authorized to use this bot.")
            return
        uid = update.effective_user.id if update.effective_user else 0
        session_id = _session_id_for_user(uid)
        connection = chat_connection_config(uid)
        args = list(context.args or [])

        async def _do_show() -> None:
            sp, err = await http_get_session_prompt(connection, session_id)
            if err:
                await update.message.reply_text(_truncate_for_telegram(err))
                return
            gp, err2 = await http_get_global_system_prompt(connection)
            if err2:
                await update.message.reply_text(_truncate_for_telegram(err2))
                return
            if sp.get("is_custom") and sp.get("system_prompt"):
                effective = str(sp["system_prompt"])
                label = "Session override"
            else:
                effective = str(gp.get("system_prompt") or "")
                label = "Global default"
            text = format_effective_prompt_reply(effective=effective, source_label=label)
            await _send_long_text(lambda t: update.message.reply_text(t), text)

        if not args or (len(args) == 1 and args[0].lower() in ("show", "get")):
            await _do_show()
            return
        if args[0].lower() in ("help", "?"):
            await update.message.reply_text(_system_help_text())
            return
        if args[0].lower() == "reset":
            ok, err = await http_delete_session_prompt(connection, session_id)
            if ok:
                await update.message.reply_text("Your addendum is cleared; Yumi's defaults still apply.")
            else:
                await update.message.reply_text(_truncate_for_telegram(f"Failed: {err}"))
            return
        if args[0].lower() == "set":
            rest = " ".join(args[1:]).strip()
            if not rest:
                await update.message.reply_text("Usage: /system set <prompt text>")
                return
            ok, err = await http_put_session_prompt(connection, session_id, rest)
            if ok:
                await update.message.reply_text("Your prompt addendum is saved (appended after Yumi's defaults).")
            else:
                await update.message.reply_text(_truncate_for_telegram(f"Failed: {err}"))
            return
        await update.message.reply_text("Unknown subcommand. Send /system help for usage.")

    async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Must answer the callback quickly; unblock the Future so /chat can continue.

        With default sequential updates, the message handler would still be awaiting the
        HTTP stream + confirmation Future—callback updates never run (deadlock). The app
        is built with ``concurrent_updates(True)`` so this handler runs in parallel.
        """
        query = update.callback_query
        if not query or not query.data:
            return
        data = query.data
        if not data.startswith("tc|"):
            return
        parts = data.split("|")
        if len(parts) != 3:
            await query.answer()
            return
        _, short_id, action = parts
        if action not in ("deny", "allow", "always"):
            await query.answer()
            return
        fut = _PENDING_TOOL_CONFIRM.pop(short_id, None)
        if fut is None or fut.done():
            await query.answer("Confirmation expired or already used.", show_alert=True)
            return
        await query.answer()
        fut.set_result(action)

    async def _append_saved_paths_from_telegram_media(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        session_id: str,
        parts: list[str],
    ) -> bool:
        """Download photo / document into ``~/.yumi/uploads/<session_id>/`` and append paths.

        Returns False if a fatal error was already reported to the user (stop processing).
        """
        msg = update.message
        if not msg:
            return True

        if msg.photo:
            photo = msg.photo[-1]
            file_id = photo.file_id
            try:
                tg_file = await context.bot.get_file(file_id)
                data = await tg_file.download_as_bytearray()
            except Exception as exc:
                await msg.reply_text(_truncate_for_telegram(f"Could not download image from Telegram: {exc}"))
                return False
            if len(data) > MAX_UPLOAD_BYTES:
                await msg.reply_text(f"Image too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).")
                return False
            name = f"telegram_photo_{photo.file_unique_id}.jpg"
            try:
                res = save_uploaded_file(session_id, name, bytes(data))
            except HTTPException as exc:
                await msg.reply_text(_truncate_for_telegram(f"Could not save image: {exc.detail}"))
                return False
            parts.append(res["path"])

        if msg.document:
            doc = msg.document
            if doc.file_size and doc.file_size > MAX_UPLOAD_BYTES:
                await msg.reply_text(f"File too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).")
                return False
            try:
                tg_file = await context.bot.get_file(doc.file_id)
                data = await tg_file.download_as_bytearray()
            except Exception as exc:
                await msg.reply_text(_truncate_for_telegram(f"Could not download file from Telegram: {exc}"))
                return False
            if len(data) > MAX_UPLOAD_BYTES:
                await msg.reply_text(f"File too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).")
                return False
            name = doc.file_name or f"telegram_doc_{doc.file_unique_id}"
            try:
                res = save_uploaded_file(session_id, name, bytes(data))
            except HTTPException as exc:
                await msg.reply_text(_truncate_for_telegram(f"Could not save file: {exc.detail}"))
                return False
            parts.append(res["path"])

        return True

    async def _append_transcribed_telegram_audio(
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        connection: ConnectionConfig,
        session_id: str,
        parts: list[str],
    ) -> bool:
        msg = update.message
        if not msg:
            return True
        voice = msg.voice
        audio = msg.audio
        if not voice and not audio:
            return True
        media = voice or audio
        audio_bytes = getattr(media, "file_size", None)
        if audio_bytes is not None and audio_bytes > MAX_UPLOAD_BYTES:
            await msg.reply_text(f"Audio too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).")
            return False
        try:
            tg_file = await context.bot.get_file(media.file_id)
            data = await tg_file.download_as_bytearray()
        except Exception as exc:
            await msg.reply_text(_truncate_for_telegram(f"Could not download audio from Telegram: {exc}"))
            return False
        if len(data) > MAX_UPLOAD_BYTES:
            await msg.reply_text(f"Audio too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).")
            return False
        if audio and audio.file_name:
            filename = audio.file_name
        else:
            filename = f"telegram_voice_{media.file_unique_id}.ogg"
        ok, text = await _post_stt_transcribe(connection, session_id=session_id, filename=filename, data=bytes(data))
        if not ok:
            await msg.reply_text(_truncate_for_telegram(f"Voice transcription failed: {text}"))
            return False
        if not text:
            await msg.reply_text("Voice transcription did not produce any text.")
            return False
        parts.append(text)
        return True

    async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message:
            return
        if not _authorized(update.effective_user.id if update.effective_user else None):
            await update.message.reply_text("You are not authorized to use this bot.")
            return

        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        session_id = _session_id_for_user(user_id)
        connection = chat_connection_config(update.effective_user.id if update.effective_user else None)

        parts: list[str] = []
        caption_or_text = (update.message.text or update.message.caption or "").strip()
        if caption_or_text:
            parts.append(caption_or_text)

        if update.message.voice or update.message.audio:
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            ok = await _append_transcribed_telegram_audio(update, context, connection, session_id, parts)
            if not ok:
                return

        if update.message.photo or update.message.document:
            ok = await _append_saved_paths_from_telegram_media(update, context, session_id, parts)
            if not ok:
                return

        if not parts:
            return

        prompt = "\n".join(parts)
        record_user_message(session_id)

        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

        url = _chat_url(connection)
        headers = connection.auth_headers()
        headers["Content-Type"] = "application/json"
        payload = {"prompt": prompt, "session_id": session_id}
        timeout = httpx.Timeout(10.0, read=600.0)

        handler = _TelegramChatHandler(context=context, chat_id=chat_id, connection=connection)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", errors="replace")
                    await update.message.reply_text(
                        _truncate_for_telegram(f"HTTP {response.status_code}: {body[:500]}")
                    )
                    return
                await consume_chat_stream(_iter_chat_events_from_http_stream(response), handler)

        final = handler.final_text()
        if final:
            from yumi.core.features.tts.reply_mode import is_voice_reply

            spoke = is_voice_reply("telegram", chat_id) and await _send_voice_reply(context, chat_id, final)
            if not spoke:
                await _send_long_text(lambda t: update.message.reply_text(t), final)

    async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        _LOG.exception("Telegram handler error", exc_info=context.error)
        if update is not None and getattr(update, "effective_message", None):
            try:
                await update.effective_message.reply_text(
                    _truncate_for_telegram("Something went wrong. Please try again or check server logs.")
                )
            except Exception:
                pass

    app = Application.builder().token(token).concurrent_updates(True).build()
    app.add_error_handler(on_error)
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("link", link_cmd))
    app.add_handler(CommandHandler("voice", voice_cmd))
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(CommandHandler("start_log", start_log_cmd))
    app.add_handler(CommandHandler("end_log", end_log_cmd))
    app.add_handler(CommandHandler("model", model_cmd))
    app.add_handler(CommandHandler("system", system_cmd))
    app.add_handler(CommandHandler("timers", timers_cmd))
    app.add_handler(CommandHandler("cancel_timer", cancel_timer_cmd))
    app.add_handler(CallbackQueryHandler(on_callback, pattern=r"^tc\|"))
    # Text, photos, and documents (files). Images are inlined for vision-capable chat models;
    # other paths are read via the server `read_file` tool when needed.
    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.PHOTO | filters.Document.ALL | filters.VOICE | filters.AUDIO) & ~filters.COMMAND,
            on_message,
        )
    )

    return app


def run_telegram_bot_sync() -> None:
    """Entry point: run polling until Ctrl+C."""
    app = build_application()
    app.run_polling(close_loop=False)
