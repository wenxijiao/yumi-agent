"""Discord client for Yumi: forwards messages to POST /chat (NDJSON) and handles tool confirmations."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from yumi.core.features.config import get_discord_allowed_user_ids, get_discord_bot_token
from yumi.core.features.proactive import record_user_message
from yumi.core.features.prompts.http_bridge import (
    format_effective_prompt_reply,
    http_delete_session_prompt,
    http_get_global_system_prompt,
    http_get_session_prompt,
    http_put_session_prompt,
)
from yumi.core.platform.http.events import ErrorEvent, TextEvent, ToolConfirmationEvent, parse_chat_event
from yumi.core.platform.http.stream_consumer import BaseChannelHandler, consume_chat_stream
from yumi.core.platform.security.connection import ConnectionConfig
from yumi.discord.bridge import chat_connection_config
from yumi.logging_config import get_logger

_MAX_MSG_LEN = 2000
_LOG = get_logger(__name__)


def _truncate_for_discord(text: str, max_chars: int = 1994) -> str:
    """Discord rejects message ``content`` longer than 2000 characters."""
    s = text if isinstance(text, str) else str(text)
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 1] + "…"


def _api_url(connection: ConnectionConfig, path: str) -> str:
    return f"{connection.base_url.rstrip('/')}{path}"


def _chat_url(connection: ConnectionConfig) -> str:
    return f"{connection.base_url.rstrip('/')}/chat"


def _session_id_for_user(discord_user_id: int) -> str:
    from yumi.core.platform.plugins import get_bridge_scope

    return get_bridge_scope().session_id("discord", str(discord_user_id))


def _split_discord_text(text: str) -> list[str]:
    # Discord rejects content longer than 2000 chars; keep a small margin and
    # split into whole chunks (never truncate — splitting is lossless).
    limit = _MAX_MSG_LEN - 10
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    rest = text
    while rest:
        chunks.append(rest[:limit])
        rest = rest[limit:]
    return chunks


async def _send_long_text(send: Callable[[str], Awaitable[Any]], text: str) -> None:
    for chunk in _split_discord_text(text):
        await send(chunk)


async def _iter_chat_events_from_http_stream(response: httpx.Response):
    """Parse one HTTP NDJSON ``response`` body into typed :class:`ChatEvent` objects.

    Decode chunks as UTF-8, split on ``\\n``, drop blank lines, validate each
    via :func:`parse_chat_event`. Validation errors are silently skipped so a
    malformed line never wedges the consumer.
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


def _build_confirmation_view(future: asyncio.Future[str], timeout: float):
    """Return a ``discord.ui.View`` with Deny / Allow / Always-allow buttons.

    Each button resolves ``future`` with ``deny`` / ``allow`` / ``always`` —
    the Discord-native equivalent of the Telegram inline-keyboard tap.
    """
    import discord

    class _ConfirmView(discord.ui.View):
        def __init__(self) -> None:
            super().__init__(timeout=timeout)

        async def _resolve(self, interaction: "discord.Interaction", action: str) -> None:
            if not future.done():
                future.set_result(action)
            for child in self.children:
                child.disabled = True  # type: ignore[attr-defined]
            try:
                await interaction.response.edit_message(view=self)
            except Exception:
                pass
            self.stop()

        @discord.ui.button(label="Deny", style=discord.ButtonStyle.danger)
        async def deny(self, interaction: "discord.Interaction", button: "discord.ui.Button") -> None:
            await self._resolve(interaction, "deny")

        @discord.ui.button(label="Allow", style=discord.ButtonStyle.success)
        async def allow(self, interaction: "discord.Interaction", button: "discord.ui.Button") -> None:
            await self._resolve(interaction, "allow")

        @discord.ui.button(label="Always allow", style=discord.ButtonStyle.secondary)
        async def always(self, interaction: "discord.Interaction", button: "discord.ui.Button") -> None:
            await self._resolve(interaction, "always")

    return _ConfirmView()


class _DiscordChatHandler(BaseChannelHandler):
    """Discord-flavoured rendering for one ``/chat`` turn.

    * ``text`` chunks accumulate into ``self.text_parts`` and are sent in one
      ``send_long_text`` call after the stream ends.
    * ``tool_confirmation`` posts a ``discord.ui.View`` with Approve/Deny
      buttons and waits for the user's click (resolved via an ``asyncio.Future``).
    * ``error`` sends a single message containing the error content.
    * ``thought`` / ``tool_status`` are dropped — Discord has no good UI for them.
    """

    CONFIRMATION_TIMEOUT_SECONDS = 600.0
    _DECISION_MAP = {"deny": "deny", "allow": "allow", "always": "always_allow"}

    def __init__(self, *, channel, connection: ConnectionConfig) -> None:
        self.channel = channel
        self.connection = connection
        self.text_parts: list[str] = []

    async def on_text(self, event: TextEvent) -> None:
        self.text_parts.append(event.content)

    async def on_tool_confirmation(self, event: ToolConfirmationEvent) -> None:
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        args_preview = json.dumps(event.arguments, ensure_ascii=False)[:800]
        text = _truncate_for_discord(
            f"Tool confirmation required\n\nTool: {event.tool_name}\nArguments: {args_preview}"
        )
        view = _build_confirmation_view(future, self.CONFIRMATION_TIMEOUT_SECONDS)
        await self.channel.send(content=text, view=view)
        try:
            action = await asyncio.wait_for(future, timeout=self.CONFIRMATION_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            await self.channel.send(content="Confirmation timed out.")
            action = "deny"
        decision = self._DECISION_MAP.get(action, "deny")
        ok, err = await _post_tool_confirm(self.connection, event.call_id, decision)
        if not ok:
            await self.channel.send(content=_truncate_for_discord(f"Confirm failed: {err}"))

    async def on_error(self, event: ErrorEvent) -> None:
        await self.channel.send(content=_truncate_for_discord(f"Error: {event.content}"))

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


def _format_timer_list_for_discord(timers: list[dict[str, Any]]) -> str:
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
    lines.append("\nCancel with !cancel_timer <id>")
    return "\n\n".join(lines)


def _authorized(user_id: int | None) -> bool:
    if user_id is None:
        return False
    allowed = get_discord_allowed_user_ids()
    if not allowed:
        return True
    return user_id in allowed


_HELP_TEXT = (
    "Yumi Discord bridge.\n\n"
    "Send a message to chat. Commands (prefix `!`):\n"
    "!voice on|off — reply with audio instead of text\n"
    "!clear — clear this chat's history\n"
    "!model — show server model config\n"
    "!system — view or change this chat's system prompt (not global)\n"
    "!timers — list active timers and scheduled tasks\n"
    "!cancel_timer <id> — cancel a timer or scheduled task\n"
    "!start_log — write full chat traces to ~/.yumi/debug/chat_trace/ (this session)\n"
    "!end_log — stop chat tracing\n"
    "!help — this message"
)


def _system_help_text() -> str:
    return (
        "!system — Your personal prompt addendum (Discord session)\n\n"
        "Your text is APPENDED to Yumi's built-in defaults and any per-app\n"
        "context, not used as a full replacement. Use it for personal\n"
        "preferences like 'always reply in English' or 'I'm a software engineer'.\n\n"
        "!system — or !system show — show the full composed prompt\n"
        "!system set <text> — set your addendum for this Discord session\n"
        "!system reset — clear your addendum (defaults still apply)\n"
        "!system help — this help"
    )


def build_client():
    """Build and return a discord.py ``commands.Bot`` (v2+)."""
    try:
        from discord.ext import commands

        import discord
    except ImportError as exc:
        raise RuntimeError(
            "Failed to import discord.py (ships with yumi-agent). Reinstall: pip install --force-reinstall yumi-agent"
        ) from exc

    token = get_discord_bot_token()
    if not token:
        raise RuntimeError(
            "Discord bot token not set. Set DISCORD_BOT_TOKEN or add discord_bot_token to ~/.yumi/config.json"
        )

    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

    async def _reply(message, text: str) -> None:
        # _send_long_text already splits to safe chunk sizes — don't re-truncate.
        await _send_long_text(message.channel.send, text)

    async def _send_voice_reply(channel, text: str) -> bool:
        """Synthesize *text* and post it as an audio attachment. Returns False on
        any failure so the caller can fall back to plain text."""
        import io

        try:
            from yumi.core.features.tts.playback import synthesize_with_fallback

            audio = await synthesize_with_fallback(text)
            file = discord.File(io.BytesIO(audio.data), filename=f"reply.{audio.format or 'wav'}")
            await channel.send(content=_truncate_for_discord(text) or None, file=file)
            return True
        except Exception as exc:  # synthesis or upload failed
            _LOG.warning("discord: voice reply failed, falling back to text: %s", exc)
            return False

    @bot.event
    async def on_ready() -> None:
        _LOG.info("Discord bot connected as %s", bot.user)

    @bot.command(name="start")
    async def start_cmd(ctx) -> None:
        if not _authorized(ctx.author.id):
            await ctx.send("You are not authorized to use this bot.")
            return
        await _reply(ctx.message, _HELP_TEXT)

    @bot.command(name="help")
    async def help_cmd(ctx) -> None:
        await start_cmd(ctx)

    @bot.command(name="link")
    async def link_cmd(ctx, code: str | None = None) -> None:
        # !link binds this Discord account to a Yumi account in multi-user
        # deployments (BridgeScope plugin). The single-user default just says no
        # binding is needed.
        from yumi.core.platform.plugins import get_bridge_scope

        reply = get_bridge_scope().link("discord", str(ctx.author.id), (code or "").strip())
        await ctx.send(reply)

    @bot.command(name="voice")
    async def voice_cmd(ctx, mode: str | None = None) -> None:
        if not _authorized(ctx.author.id):
            await ctx.send("You are not authorized to use this bot.")
            return
        from yumi.core.features.tts.reply_mode import is_voice_reply, set_voice_reply

        channel_id = ctx.channel.id
        arg = (mode or "").strip().lower()
        if arg in ("on", "off"):
            set_voice_reply("discord", channel_id, arg == "on")
            await ctx.send(
                "Voice replies are ON — I'll answer with audio." if arg == "on" else "Voice replies are OFF."
            )
            return
        state = "ON" if is_voice_reply("discord", channel_id) else "OFF"
        await ctx.send(f"Voice replies are {state}. Use !voice on or !voice off.")

    @bot.command(name="clear")
    async def clear_cmd(ctx) -> None:
        if not _authorized(ctx.author.id):
            await ctx.send("You are not authorized to use this bot.")
            return
        session_id = _session_id_for_user(ctx.author.id)
        connection = chat_connection_config(ctx.author.id)
        ok, err = await _post_clear_session(connection, session_id)
        if ok:
            await ctx.send("Session cleared.")
        else:
            await ctx.send(_truncate_for_discord(f"Failed to clear: {err}"))

    @bot.command(name="start_log")
    async def start_log_cmd(ctx) -> None:
        if not _authorized(ctx.author.id):
            await ctx.send("You are not authorized to use this bot.")
            return
        session_id = _session_id_for_user(ctx.author.id)
        connection = chat_connection_config(ctx.author.id)
        ok, err, data = await _put_chat_debug(connection, session_id, True)
        if not ok:
            await ctx.send(_truncate_for_discord(f"Failed to start debug log: {err}"))
            return
        path = (data or {}).get("trace_path") or ""
        await ctx.send(
            _truncate_for_discord(
                "Chat debug logging ON for this session.\n"
                f"Trace file: {path}\n"
                "Logs include turn boundaries, each full LLM request (messages + tools), and stream events.\n"
                "Optional: set YUMI_CHAT_DEBUG_REDACT_IMAGE_DATA=1 on the server to shorten inline data-URL "
                "images in the trace file only.\n"
                "Send !end_log to stop."
            )
        )

    @bot.command(name="end_log")
    async def end_log_cmd(ctx) -> None:
        if not _authorized(ctx.author.id):
            await ctx.send("You are not authorized to use this bot.")
            return
        session_id = _session_id_for_user(ctx.author.id)
        connection = chat_connection_config(ctx.author.id)
        ok, err, data = await _put_chat_debug(connection, session_id, False)
        if not ok:
            await ctx.send(_truncate_for_discord(f"Failed to end debug log: {err}"))
            return
        path = (data or {}).get("trace_path") or ""
        if path:
            await ctx.send(_truncate_for_discord(f"Chat debug logging OFF. Last trace file:\n{path}"))
        else:
            await ctx.send("Chat debug logging was not active for this session.")

    @bot.command(name="timers")
    async def timers_cmd(ctx) -> None:
        if not _authorized(ctx.author.id):
            await ctx.send("You are not authorized to use this bot.")
            return
        connection = chat_connection_config(ctx.author.id)
        ok, err, timers = await _get_timers(connection)
        if not ok:
            await ctx.send(_truncate_for_discord(f"Failed to list timers: {err}"))
            return
        await _reply(ctx.message, _format_timer_list_for_discord(timers))

    @bot.command(name="cancel_timer")
    async def cancel_timer_cmd(ctx, timer_id: str | None = None) -> None:
        if not _authorized(ctx.author.id):
            await ctx.send("You are not authorized to use this bot.")
            return
        if not timer_id or not str(timer_id).strip():
            await ctx.send("Usage: !cancel_timer <timer_id>")
            return
        timer_id = str(timer_id).strip()
        connection = chat_connection_config(ctx.author.id)
        ok, message = await _delete_timer(connection, timer_id)
        if ok:
            await ctx.send(_truncate_for_discord(message or f"Cancelled {timer_id}."))
        else:
            await ctx.send(_truncate_for_discord(message or f"Failed to cancel {timer_id}."))

    @bot.command(name="model")
    async def model_cmd(ctx) -> None:
        if not _authorized(ctx.author.id):
            await ctx.send("You are not authorized to use this bot.")
            return
        connection = chat_connection_config(ctx.author.id)
        cfg = await _get_model_config(connection)
        if not cfg:
            await ctx.send("Could not read /config/model from the server.")
            return
        lines = [
            f"Chat: {cfg.get('chat_provider', '?')} / {cfg.get('chat_model', '?')}",
            f"Embedding: {cfg.get('embedding_provider', '?')} / {cfg.get('embedding_model', '?')}",
        ]
        await ctx.send("\n".join(lines))

    @bot.command(name="system")
    async def system_cmd(ctx, *, rest: str = "") -> None:
        if not _authorized(ctx.author.id):
            await ctx.send("You are not authorized to use this bot.")
            return
        session_id = _session_id_for_user(ctx.author.id)
        connection = chat_connection_config(ctx.author.id)
        args = rest.split()

        async def _do_show() -> None:
            sp, err = await http_get_session_prompt(connection, session_id)
            if err:
                await ctx.send(_truncate_for_discord(err))
                return
            gp, err2 = await http_get_global_system_prompt(connection)
            if err2:
                await ctx.send(_truncate_for_discord(err2))
                return
            if sp.get("is_custom") and sp.get("system_prompt"):
                effective = str(sp["system_prompt"])
                label = "Session override"
            else:
                effective = str(gp.get("system_prompt") or "")
                label = "Global default"
            text = format_effective_prompt_reply(effective=effective, source_label=label)
            await _reply(ctx.message, text)

        if not args or (len(args) == 1 and args[0].lower() in ("show", "get")):
            await _do_show()
            return
        if args[0].lower() in ("help", "?"):
            await ctx.send(_system_help_text())
            return
        if args[0].lower() == "reset":
            ok, err = await http_delete_session_prompt(connection, session_id)
            if ok:
                await ctx.send("Your addendum is cleared; Yumi's defaults still apply.")
            else:
                await ctx.send(_truncate_for_discord(f"Failed: {err}"))
            return
        if args[0].lower() == "set":
            body = " ".join(args[1:]).strip()
            if not body:
                await ctx.send("Usage: !system set <prompt text>")
                return
            ok, err = await http_put_session_prompt(connection, session_id, body)
            if ok:
                await ctx.send("Your prompt addendum is saved (appended after Yumi's defaults).")
            else:
                await ctx.send(_truncate_for_discord(f"Failed: {err}"))
            return
        await ctx.send("Unknown subcommand. Send !system help for usage.")

    async def _run_chat_turn(message, prompt: str) -> None:
        user_id = message.author.id
        session_id = _session_id_for_user(user_id)
        connection = chat_connection_config(user_id)
        record_user_message(session_id)

        url = _chat_url(connection)
        headers = connection.auth_headers()
        headers["Content-Type"] = "application/json"
        payload = {"prompt": prompt, "session_id": session_id}
        timeout = httpx.Timeout(10.0, read=600.0)

        handler = _DiscordChatHandler(channel=message.channel, connection=connection)
        async with message.channel.typing():
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", url, json=payload, headers=headers) as response:
                    if response.status_code >= 400:
                        body = (await response.aread()).decode("utf-8", errors="replace")
                        await message.channel.send(_truncate_for_discord(f"HTTP {response.status_code}: {body[:500]}"))
                        return
                    await consume_chat_stream(_iter_chat_events_from_http_stream(response), handler)

        final = handler.final_text()
        if final:
            from yumi.core.features.tts.reply_mode import is_voice_reply

            spoke = is_voice_reply("discord", message.channel.id) and await _send_voice_reply(message.channel, final)
            if not spoke:
                await _reply(message, final)

    @bot.event
    async def on_message(message) -> None:
        # Ignore our own messages and any other bots.
        if message.author.bot or (bot.user is not None and message.author.id == bot.user.id):
            return
        # Let registered ``!`` commands run first; only free text falls through to chat.
        ctx = await bot.get_context(message)
        if ctx.valid:
            await bot.invoke(ctx)
            return
        if not _authorized(message.author.id):
            await message.channel.send("You are not authorized to use this bot.")
            return
        prompt = (message.content or "").strip()
        if not prompt:
            return
        await _run_chat_turn(message, prompt)

    @bot.event
    async def on_command_error(ctx, error) -> None:
        _LOG.exception("Discord command error", exc_info=error)
        try:
            await ctx.send(_truncate_for_discord("Something went wrong. Please try again or check server logs."))
        except Exception:
            pass

    return bot


def run_discord_bot_sync() -> None:
    """Entry point: run the Discord gateway connection until Ctrl+C."""
    bot = build_client()
    token = get_discord_bot_token()
    if not token:
        raise RuntimeError(
            "Discord bot token not set. Set DISCORD_BOT_TOKEN or add discord_bot_token to ~/.yumi/config.json"
        )
    bot.run(token)
