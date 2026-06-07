"""LINE webhook event handling: /chat stream, Flex cards, postbacks (OSS single-user).

Multi-tenant LINE flows (``/link``, ``/usage``, per-user model overrides,
relay-mode chat URLs) live in the ``kumi_enterprise.line`` package and
attach via the plugin system.
"""

from __future__ import annotations

import asyncio
import base64
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import HTTPException

from kumi.core.api.uploads import MAX_UPLOAD_BYTES, save_uploaded_file
from kumi.core.features.config import load_saved_model_config
from kumi.core.features.config.line import (
    get_line_allowed_user_ids,
    get_line_model_candidates,
    line_push_disabled,
)
from kumi.core.features.proactive import record_user_message
from kumi.core.features.prompts.http_bridge import (
    format_effective_prompt_reply,
    http_delete_session_prompt,
    http_get_global_system_prompt,
    http_get_session_prompt,
    http_put_session_prompt,
)
from kumi.core.features.prompts.store import (
    delete_session_prompt,
    get_effective_system_prompt,
    get_session_prompt,
    set_session_prompt,
)
from kumi.core.platform.http.events import ErrorEvent, TextEvent, ToolConfirmationEvent
from kumi.core.platform.http.stream_consumer import BaseChannelHandler, consume_chat_stream
from kumi.core.platform.plugins import (
    LOCAL_IDENTITY,
    get_current_identity,
    get_quota_policy,
    get_session_scope,
)
from kumi.core.platform.security.audit import audit_event
from kumi.core.platform.security.connection import DEFAULT_LOCAL_SERVER_URL, ConnectionConfig
from kumi.line.bridge import chat_connection_config
from kumi.line.client import LineMessagingClient, flex_message, text_message
from kumi.line.flex_builders import (
    file_upload_receipt,
    model_card,
    model_picker_carousel,
    parse_postback,
    tool_confirm_card,
)
from kumi.line.pending import (
    MODEL_PICK_SESSIONS,
    PENDING_TOOL_CONFIRM,
    TIMER_CARD_CTX,
)

_LINE_TEXT_MAX = 5000

_LINE_SYSTEM_HELP = (
    "/system — Session system prompt (LINE session only; not global)\n\n"
    "/system — or /system show — show the effective prompt\n"
    "/system set <text> — set a session override\n"
    "/system reset — clear override; use the server global default\n"
    "/system help — this help\n\n"
    "For long prompts, prefer the web UI or HTTP API."
)


def line_session_client_id(line_user_id: str) -> str:
    return f"line_{line_user_id.strip()}"


def _authorized(line_user_id: str) -> bool:
    allowed = get_line_allowed_user_ids()
    if not allowed:
        return True
    return str(line_user_id).strip() in allowed


def _api_url(connection: ConnectionConfig, path: str) -> str:
    return f"{connection.base_url.rstrip('/')}{path}"


def _chat_url(connection: ConnectionConfig) -> str:
    return f"{connection.base_url.rstrip('/')}/chat"


def _split_line_text(text: str) -> list[str]:
    if len(text) <= _LINE_TEXT_MAX:
        return [text]
    chunks: list[str] = []
    rest = text
    while rest:
        chunks.append(rest[:_LINE_TEXT_MAX])
        rest = rest[_LINE_TEXT_MAX:]
    return chunks


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


async def _transcribe_audio_bytes(
    line_user_id: str,
    *,
    session_id: str,
    filename: str,
    data: bytes,
    use_http: bool,
) -> str:
    if use_http:
        connection = chat_connection_config(line_user_id)
        url = _api_url(connection, "/stt/transcribe")
        headers = connection.auth_headers()
        headers["Content-Type"] = "application/json"
        timeout = httpx.Timeout(10.0, read=600.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(
                url,
                headers=headers,
                json={
                    "session_id": session_id,
                    "filename": filename,
                    "content_base64": base64.standard_b64encode(data).decode("ascii"),
                },
            )
            if r.status_code >= 400:
                raise RuntimeError(r.text[:500])
            return str(r.json().get("text") or "").strip()

    from kumi.core.features.stt import transcribe_audio

    result = await transcribe_audio(data, filename=filename)
    return result.text.strip()


async def _line_system_command(
    line_user_id: str,
    client_session_id: str,
    tail: str,
    *,
    use_http: bool,
) -> str:
    t = tail.strip()
    if t.lower() in ("help", "?"):
        return _LINE_SYSTEM_HELP

    parts_sys = t.split(maxsplit=1)
    verb = parts_sys[0].lower() if parts_sys else ""
    arg_rest = parts_sys[1] if len(parts_sys) > 1 else ""

    ident = LOCAL_IDENTITY
    sid = get_session_scope().qualify_session_id(ident, client_session_id)

    if not verb or verb in ("show", "get"):
        if use_http:
            connection = chat_connection_config(line_user_id)
            sp, err = await http_get_session_prompt(connection, client_session_id)
            if err:
                return err
            gp, err2 = await http_get_global_system_prompt(connection)
            if err2:
                return err2
            if sp.get("is_custom") and sp.get("system_prompt"):
                effective = str(sp["system_prompt"])
                label = "Session override"
            else:
                effective = str(gp.get("system_prompt") or "")
                label = "Global default"
            return format_effective_prompt_reply(effective=effective, source_label=label)

        custom = get_session_prompt(sid)
        eff = get_effective_system_prompt(sid)
        label = "Session override" if custom else "Global default"
        return format_effective_prompt_reply(effective=eff, source_label=label)

    if verb == "reset":
        if use_http:
            connection = chat_connection_config(line_user_id)
            ok, err = await http_delete_session_prompt(connection, client_session_id)
        else:
            delete_session_prompt(sid)
            ok, err = True, ""
        if ok:
            return "Session override cleared; using the global system prompt."
        return f"Failed: {err}"

    if verb == "set":
        body = arg_rest.strip()
        if not body:
            return "Usage: /system set <prompt text>"
        if use_http:
            connection = chat_connection_config(line_user_id)
            ok, err = await http_put_session_prompt(connection, client_session_id, body)
        else:
            set_session_prompt(sid, body)
            ok, err = True, ""
        if ok:
            return "Session system prompt updated."
        return f"Failed: {err}"

    return "Unknown subcommand. Send /system help for usage."


async def _stream_chat_http(line_user_id: str, prompt: str, session_id: str) -> AsyncIterator[dict[str, Any]]:
    connection = chat_connection_config(line_user_id)
    url = _chat_url(connection)
    headers = connection.auth_headers()
    headers["Content-Type"] = "application/json"
    timeout = httpx.Timeout(10.0, read=600.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST",
            url,
            json={"prompt": prompt, "session_id": session_id},
            headers=headers,
        ) as response:
            if response.status_code >= 400:
                body = (await response.aread()).decode("utf-8", errors="replace")
                yield {"type": "error", "content": f"HTTP {response.status_code}: {body[:500]}"}
                return
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
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(event, dict):
                        yield event


async def _stream_chat_direct(line_user_id: str, prompt: str, session_id: str) -> AsyncIterator[dict[str, Any]]:
    ident = get_current_identity()
    quota = get_quota_policy()
    allowed, qerr = quota.check_chat_allowed(ident)
    if not allowed:
        yield {"type": "error", "content": qerr or "quota exceeded"}
        return
    tok_ok, tok_err = quota.check_token_quota(ident)
    if not tok_ok:
        yield {"type": "error", "content": tok_err or "token quota exceeded"}
        return
    sid = get_session_scope().qualify_session_id(ident, session_id)
    quota.record_chat_turn(ident)
    audit_event("chat_request", ident.user_id, session_id=sid, source="line", line_user_id=line_user_id)
    from kumi.core.api.chat import generate_chat_events

    async for ev in generate_chat_events(prompt, sid, think=False):
        yield ev


async def stream_line_chat(
    line_user_id: str,
    prompt: str,
    session_id: str,
    *,
    use_http: bool,
) -> AsyncIterator[dict[str, Any]]:
    if use_http:
        async for ev in _stream_chat_http(line_user_id, prompt, session_id):
            yield ev
    else:
        async for ev in _stream_chat_direct(line_user_id, prompt, session_id):
            yield ev


async def _send_messages(
    line_client: LineMessagingClient,
    reply_token: str | None,
    user_id: str,
    messages: list[dict[str, Any]],
    *,
    started_monotonic: float,
    prefer_push: bool = False,
) -> None:
    if line_push_disabled() or not messages:
        return
    use_push = prefer_push or (not reply_token)
    if not use_push:
        elapsed = __import__("time").monotonic() - started_monotonic
        if elapsed > 25.0:
            use_push = True
    if use_push:
        await line_client.push_message(user_id, messages)
        return
    try:
        await line_client.reply_message(reply_token or "", messages)
    except Exception:
        await line_client.push_message(user_id, messages)


class _LineChatHandler(BaseChannelHandler):
    """LINE-flavoured rendering for one ``/chat`` turn.

    Behaviour matches the four hand-rolled message-loop blocks that previously
    lived inline in ``handle_line_message_event``:

    * ``text`` chunks accumulate into ``self.text_parts`` (final reply built once
      the stream ends).
    * ``tool_confirmation`` pushes a Flex confirmation card, awaits the user's
      Flex-postback decision via :data:`PENDING_TOOL_CONFIRM`, then forwards the
      decision to the OSS ``/tools/confirm`` endpoint.
    * ``error`` pushes a plain-text "Error: ..." reply.
    * ``thought`` / ``tool_status`` are dropped — LINE has no good UI for them.
    """

    CONFIRMATION_TIMEOUT_SECONDS = 600.0
    _DECISION_MAP = {"deny": "deny", "allow": "allow", "always": "always_allow"}

    def __init__(
        self,
        *,
        line_client: LineMessagingClient,
        line_user_id: str,
        reply_token: str | None,
        connection: ConnectionConfig,
        started_monotonic: float,
    ) -> None:
        self.line_client = line_client
        self.line_user_id = line_user_id
        self.reply_token = reply_token
        self.connection = connection
        self.started_monotonic = started_monotonic
        self.text_parts: list[str] = []

    async def on_text(self, event: TextEvent) -> None:
        self.text_parts.append(event.content)

    async def on_tool_confirmation(self, event: ToolConfirmationEvent) -> None:
        short_id = uuid.uuid4().hex[:8]
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        PENDING_TOOL_CONFIRM[short_id] = future
        args_preview = json.dumps(event.arguments, ensure_ascii=False)[:800]
        bubble = tool_confirm_card(event.tool_name, args_preview, short_id)
        try:
            await self.line_client.push_message(self.line_user_id, [flex_message("Confirm", bubble)])
        except Exception:
            pass
        try:
            action = await asyncio.wait_for(future, timeout=self.CONFIRMATION_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            action = "deny"
        finally:
            PENDING_TOOL_CONFIRM.pop(short_id, None)
        decision = self._DECISION_MAP.get(action, "deny")
        ok, err = await _post_tool_confirm(self.connection, event.call_id, decision)
        if not ok:
            await self._reply_text(f"Confirmation failed: {err}", push=True)

    async def on_error(self, event: ErrorEvent) -> None:
        await self._reply_text(f"Error: {event.content}", push=True)

    def final_text(self) -> str:
        return "".join(self.text_parts)

    async def _reply_text(self, text: str, *, push: bool = False) -> None:
        msgs = [text_message(p) for p in _split_line_text(text)]
        await _send_messages(
            self.line_client,
            self.reply_token,
            self.line_user_id,
            msgs,
            started_monotonic=self.started_monotonic,
            prefer_push=push,
        )


async def _run_line_chat_turn(
    *,
    line_client: LineMessagingClient,
    line_user_id: str,
    prompt: str,
    session_id: str,
    reply_token: str | None,
    connection: ConnectionConfig,
    started_monotonic: float,
    use_http: bool,
    prefix_messages: list[dict[str, Any]] | None = None,
) -> None:
    """Drive one chat turn through ``stream_line_chat`` + send the final reply.

    ``prefix_messages`` is for media-receipt bubbles that should be prepended
    to the assistant's text reply (image/file path).
    """
    handler = _LineChatHandler(
        line_client=line_client,
        line_user_id=line_user_id,
        reply_token=reply_token,
        connection=connection,
        started_monotonic=started_monotonic,
    )
    await consume_chat_stream(
        stream_line_chat(line_user_id, prompt, session_id, use_http=use_http),
        handler,
    )
    final_text = handler.final_text()
    msgs: list[dict[str, Any]] = list(prefix_messages or [])
    if final_text:
        msgs.extend(text_message(chunk) for chunk in _split_line_text(final_text))
    if msgs:
        await _send_messages(
            line_client,
            reply_token,
            line_user_id,
            msgs,
            started_monotonic=started_monotonic,
        )


async def _get_model_dict(line_user_id: str, *, use_http: bool) -> dict[str, Any] | None:
    if use_http:
        connection = chat_connection_config(line_user_id)
        url = _api_url(connection, "/config/model")
        headers = connection.auth_headers()
        timeout = httpx.Timeout(10.0, read=30.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.get(url, headers=headers)
            if r.status_code >= 400:
                return None
            return r.json()
    cfg = load_saved_model_config()
    from kumi.core.features.config import get_api_credentials

    creds = get_api_credentials()
    return {
        "chat_provider": cfg.chat_provider,
        "chat_model": cfg.chat_model or "",
        "embedding_provider": cfg.embedding_provider,
        "embedding_model": cfg.embedding_model or "",
        "openai_api_key_saved": bool(cfg.openai_api_key and str(cfg.openai_api_key).strip()),
        "gemini_api_key_saved": bool(cfg.gemini_api_key and str(cfg.gemini_api_key).strip()),
        "claude_api_key_saved": bool(cfg.claude_api_key and str(cfg.claude_api_key).strip()),
        "deepseek_api_key_saved": bool(cfg.deepseek_api_key and str(cfg.deepseek_api_key).strip()),
        "openai_api_key_effective": bool(creds.get("openai_api_key")),
        "gemini_api_key_effective": bool(creds.get("gemini_api_key")),
        "claude_api_key_effective": bool(creds.get("claude_api_key")),
        "deepseek_api_key_effective": bool(creds.get("deepseek_api_key")),
    }


async def _apply_chat_model(line_user_id: str, model_name: str, *, use_http: bool) -> tuple[bool, str]:
    name = (model_name or "").strip()
    if not name:
        return False, "empty model"
    if use_http:
        connection = chat_connection_config(line_user_id)
        headers = connection.auth_headers()
        timeout = httpx.Timeout(10.0, read=60.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            url = _api_url(connection, "/config/model")
            r = await client.put(
                url,
                headers={**headers, "Content-Type": "application/json"},
                json={"chat_model": name},
            )
            if r.status_code >= 400:
                return False, r.text[:500]
        return True, ""

    from kumi.core.features.config import save_model_config

    cfg = load_saved_model_config()
    cfg.chat_model = name
    save_model_config(cfg)
    return True, ""


async def handle_line_message_event(
    event: dict[str, Any],
    line_client: LineMessagingClient,
    *,
    use_http: bool,
) -> None:
    reply_tok = event.get("replyToken")
    src = event.get("source") or {}
    if src.get("type") != "user":
        return
    user_id = str(src.get("userId") or "").strip()
    if not user_id or not _authorized(user_id):
        return

    msg = event.get("message") or {}
    mtype = msg.get("type")
    started = __import__("time").monotonic()
    session_id = line_session_client_id(user_id)
    connection = chat_connection_config(user_id)

    async def reply_text(text: str, *, push: bool = False) -> None:
        parts = _split_line_text(text)
        msgs = [text_message(p) for p in parts]
        await _send_messages(line_client, reply_tok, user_id, msgs, started_monotonic=started, prefer_push=push)

    # ── commands (text) ──
    if mtype == "text":
        raw = (msg.get("text") or "").strip()
        lower = raw.lower()
        if lower in ("/help", "/start", "help"):
            await reply_text(
                "Kumi LINE bridge\n\n"
                "Send a message to chat (images/files; voice when STT is enabled).\n"
                "Commands:\n"
                "/clear — clear this session\n"
                "/model — view or switch model\n"
                "/start_log — debug: log this session's chat to ~/.kumi/debug/chat_trace/\n"
                "/end_log — stop debug logging\n"
                "/system — session system prompt (see /system help)\n"
                "/help — this message"
            )
            return
        if lower.startswith("/clear"):
            ok, err = await _post_clear_session(connection, session_id)
            if ok:
                await reply_text("Session cleared.")
            else:
                await reply_text(f"Failed to clear session: {err}")
            return
        if lower.startswith("/start_log"):
            ok, err, data = await _put_chat_debug(connection, session_id, True)
            if ok:
                p = (data or {}).get("trace_path") or ""
                await reply_text(
                    "Chat debug ON.\n"
                    f"Trace: {p}\n"
                    "Trace includes full LLM requests (messages + tools). Optional: KUMI_CHAT_DEBUG_REDACT_IMAGE_DATA=1 shortens logged image data URLs.\n"
                    "Send /end_log to stop."
                )
            else:
                await reply_text(f"Failed to start debug: {err}")
            return
        if lower.startswith("/end_log"):
            ok, err, data = await _put_chat_debug(connection, session_id, False)
            if not ok:
                await reply_text(f"Failed to end debug: {err}")
                return
            p = (data or {}).get("trace_path") or ""
            if p:
                await reply_text(f"Chat debug OFF.\nLast trace:\n{p}")
            else:
                await reply_text("Chat debug was not active.")
            return
        if lower.startswith("/model"):
            cfg = await _get_model_dict(user_id, use_http=use_http)
            if not cfg:
                await reply_text("Could not read model configuration.")
                return
            pick_sid = uuid.uuid4().hex[:8]
            bubble = model_card(
                str(cfg.get("chat_provider", "?")),
                str(cfg.get("chat_model", "?")),
                str(cfg.get("embedding_provider", "?")),
                str(cfg.get("embedding_model", "?")),
                pick_sid,
            )
            MODEL_PICK_SESSIONS[pick_sid] = list(get_line_model_candidates())
            msg_flex = flex_message("Model", bubble)
            await _send_messages(
                line_client,
                reply_tok,
                user_id,
                [msg_flex],
                started_monotonic=started,
            )
            return
        if raw.lower().startswith("/system"):
            tail = raw[len("/system") :].strip()
            out = await _line_system_command(user_id, session_id, tail, use_http=use_http)
            await reply_text(out)
            return

        prompt = raw
        if not prompt:
            return
        record_user_message(session_id)
        await _run_line_chat_turn(
            line_client=line_client,
            line_user_id=user_id,
            prompt=prompt,
            session_id=session_id,
            reply_token=reply_tok,
            connection=connection,
            started_monotonic=started,
            use_http=use_http,
        )
        return

    if mtype == "audio":
        mid = msg.get("id")
        if not mid:
            await reply_text("Could not read this voice message.")
            return
        try:
            await line_client.show_loading_animation(user_id, 20)
        except Exception:
            pass
        try:
            data = await line_client.get_message_content(str(mid))
            if len(data) > MAX_UPLOAD_BYTES:
                await reply_text(f"Audio too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).")
                return
            prompt = await _transcribe_audio_bytes(
                user_id,
                session_id=session_id,
                filename=f"line_audio_{mid}.m4a",
                data=data,
                use_http=use_http,
            )
        except Exception as exc:
            await reply_text(f"Voice transcription failed: {exc}")
            return
        if not prompt:
            await reply_text("Transcription produced no text.")
            return
        record_user_message(session_id)
        await _run_line_chat_turn(
            line_client=line_client,
            line_user_id=user_id,
            prompt=prompt,
            session_id=session_id,
            reply_token=reply_tok,
            connection=connection,
            started_monotonic=started,
            use_http=use_http,
        )
        return

    # Non-text: image / file
    if mtype in ("image", "file"):
        parts: list[str] = []
        ok_media = await _append_line_media_to_parts(msg, line_client, user_id, session_id, parts)
        if not ok_media or not parts:
            await reply_text("Could not process this media.")
            return
        prompt = "\n".join(parts)
        record_user_message(session_id)
        media_receipts: list[dict[str, Any]] = []
        if parts and (parts[0].startswith("/") or parts[0].startswith("~")):
            p0 = parts[0]
            try:
                sz = __import__("pathlib").Path(p0).stat().st_size
                name = __import__("os").path.basename(p0)
                media_receipts.append(flex_message("File", file_upload_receipt(name, sz, None)))
            except OSError:
                pass
        await _run_line_chat_turn(
            line_client=line_client,
            line_user_id=user_id,
            prompt=prompt,
            session_id=session_id,
            reply_token=reply_tok,
            connection=connection,
            started_monotonic=started,
            use_http=use_http,
            prefix_messages=media_receipts,
        )
        return

    await reply_text("Unsupported message type (send text, image, file, or voice).")


async def _append_line_media_to_parts(
    msg: dict[str, Any],
    line_client: LineMessagingClient,
    line_user_id: str,
    session_id: str,
    parts: list[str],
) -> bool:
    mtype = msg.get("type")
    mid = msg.get("id")
    if not mid:
        return True
    try:
        data = await line_client.get_message_content(str(mid))
    except Exception as exc:
        parts.clear()
        parts.append(f"(download failed: {exc})")
        return False
    if len(data) > MAX_UPLOAD_BYTES:
        parts.clear()
        parts.append(f"File too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB)")
        return False
    if mtype == "image":
        name = f"line_image_{mid}.jpg"
    else:
        name = str(msg.get("fileName") or f"line_file_{mid}")
    try:
        res = save_uploaded_file(session_id, name, data, owner_user_id=None)
    except HTTPException as exc:
        parts.clear()
        parts.append(str(exc.detail))
        return False
    parts.append(str(res.get("path", "")))
    # silence unused-arg lint while keeping stable signature for enterprise overrides
    _ = line_user_id
    return True


async def handle_line_postback_event(
    event: dict[str, Any],
    line_client: LineMessagingClient,
    *,
    use_http: bool,
) -> None:
    reply_tok = event.get("replyToken")
    src = event.get("source") or {}
    if src.get("type") != "user":
        return
    user_id = str(src.get("userId") or "").strip()
    if not user_id or not _authorized(user_id):
        return
    data = str((event.get("postback") or {}).get("data") or "")
    parsed = parse_postback(data)
    if not parsed:
        return
    verb, short_id, arg = parsed
    started = __import__("time").monotonic()

    async def reply_text(text: str, *, push: bool = False) -> None:
        msgs = [text_message(t) for t in _split_line_text(text)]
        await _send_messages(line_client, reply_tok, user_id, msgs, started_monotonic=started, prefer_push=push)

    if verb == "tool_confirm":
        fut = PENDING_TOOL_CONFIRM.get(short_id)
        if fut is None or fut.done():
            await reply_text("Confirmation expired or already used.")
            return
        if arg not in ("deny", "allow", "always"):
            arg = "deny"
        fut.set_result(arg)
        await reply_text("Choice recorded.")
        return

    if verb == "model_switch":
        if arg == "__open__":
            candidates = MODEL_PICK_SESSIONS.get(short_id) or list(get_line_model_candidates())
            car = model_picker_carousel(candidates, short_id)
            await _send_messages(
                line_client,
                reply_tok,
                user_id,
                [flex_message("Pick model", car)],
                started_monotonic=started,
            )
            return
        try:
            idx = int(arg)
        except ValueError:
            await reply_text("Invalid option.")
            return
        candidates = MODEL_PICK_SESSIONS.get(short_id) or []
        if idx < 0 or idx >= len(candidates):
            await reply_text("Invalid model index.")
            return
        model_name = candidates[idx]
        ok, err = await _apply_chat_model(user_id, model_name, use_http=use_http)
        if ok:
            await reply_text(f"Switched chat model to: {model_name}")
        else:
            await reply_text(f"Failed to switch model: {err}")
        return

    if verb == "timer_snooze":
        ctx = TIMER_CARD_CTX.get(short_id)
        if not ctx:
            await reply_text("Timer context expired.")
            return
        try:
            delay = int(arg)
        except ValueError:
            delay = 300
        from kumi.core.api.timers import schedule_timer

        schedule_timer(
            "line_snooze_" + uuid.uuid4().hex[:8],
            delay,
            str(ctx.get("description", "")),
            str(ctx.get("qualified_session_id", ctx.get("session_id", ""))),
        )
        await reply_text(f"Snoozed for about {max(1, delay // 60)} minutes.")
        return

    if verb == "timer_rerun":
        ctx = TIMER_CARD_CTX.get(short_id)
        if not ctx:
            await reply_text("Timer context expired.")
            return
        client_sid = str(ctx.get("client_session_id", line_session_client_id(user_id)))
        description = str(ctx.get("description", ""))
        prompt = (
            f"[Timer expired — scheduled action]\n"
            f"Planned task: {description}\n"
            f"Now execute it: use currently available tools only when needed, then answer the user in the same language."
        )
        # Timer-rerun postbacks always push (no reply token left); confirmations
        # in this path are unusual but we still go through the standard handler
        # so any tool that asks for approval is offered the same Flex card.
        await _run_line_chat_turn(
            line_client=line_client,
            line_user_id=user_id,
            prompt=prompt,
            session_id=client_sid,
            reply_token=None,
            connection=chat_connection_config(user_id),
            started_monotonic=started,
            use_http=use_http,
        )
        return


def verify_and_parse_line_webhook(
    body: bytes,
    x_line_signature: str | None,
) -> tuple[list[dict], LineMessagingClient]:
    """Verify the LINE signature and parse the body. Cheap, synchronous, fail-fast.

    Raises PermissionError on bad signature, ValueError on bad JSON,
    RuntimeError when LINE secret is not configured.
    """
    from kumi.core.features.config.line import get_line_channel_access_token, get_line_channel_secret

    secret = get_line_channel_secret()
    token = get_line_channel_access_token()
    if not secret:
        raise RuntimeError("LINE_CHANNEL_SECRET not configured")
    from kumi.line.client import verify_line_signature

    if not verify_line_signature(secret, body, x_line_signature):
        raise PermissionError("invalid LINE signature")

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid webhook json: {exc}") from exc

    events = payload.get("events") or []
    if not isinstance(events, list):
        return [], LineMessagingClient(token or "")
    return [e for e in events if isinstance(e, dict)], LineMessagingClient(token or "")


async def process_line_events(
    events: list[dict],
    line_client: LineMessagingClient,
    *,
    use_http: bool,
) -> None:
    """Run the full chat turn for each LINE event. Caller schedules this off the request path
    so we can return 200 within LINE's ~1s retry window."""
    from kumi.logging_config import get_logger

    log = get_logger(__name__)
    for event in events:
        et = event.get("type")
        try:
            if et == "message":
                await handle_line_message_event(event, line_client, use_http=use_http)
            elif et == "postback":
                await handle_line_postback_event(event, line_client, use_http=use_http)
            elif et == "follow":
                reply_tok = event.get("replyToken")
                src = event.get("source") or {}
                uid = str(src.get("userId") or "")
                if uid and line_client.token_configured and not line_push_disabled():
                    try:
                        await line_client.reply_message(
                            reply_tok or "",
                            [text_message("Kumi LINE is ready. Send /help for commands.")],
                        )
                    except Exception:
                        pass
        except Exception:
            log.exception("LINE event handler error")


async def dispatch_line_webhook(
    body: bytes,
    x_line_signature: str | None,
    *,
    use_http: bool,
) -> None:
    """Synchronous variant kept for back-compat: verify + run events inline."""
    events, line_client = verify_and_parse_line_webhook(body, x_line_signature)
    await process_line_events(events, line_client, use_http=use_http)


# Re-exported for enterprise overrides that import them by name.
__all__ = (
    "dispatch_line_webhook",
    "verify_and_parse_line_webhook",
    "process_line_events",
    "DEFAULT_LOCAL_SERVER_URL",
)
