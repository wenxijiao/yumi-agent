import asyncio
import base64
import json
import os
import queue
import threading
import uuid
from pathlib import Path
from typing import Any

import reflex as rx
import requests
from pydantic import BaseModel
from yumi.core.features.memory.tool_replay import message_hidden_from_chat_ui
from yumi.logging_config import get_logger
from yumi.ui.ui.constants import (
    _MONITOR_POLL_JS,
    _TIMER_POLL_JS,
    ACCENT,
    CHAT_INPUT_RESET_HEIGHT_JS,
    CHAT_INPUT_RESIZE_FOCUS_JS,
    CUSTOM_CSS,
    DEFAULT_SERVER_URL,
    SB_BG,
    SB_BORDER,
    SB_HOVER,
    SB_TEXT,
    SB_TEXT_HI,
    SCROLL_SCRIPT,
    TEXTAREA_SCRIPT,
)
from yumi.ui.ui.timer_listener import start_timer_listener, timer_event_queue

logger = get_logger(__name__)

_MAX_CHAT_UPLOAD_BYTES = 25 * 1024 * 1024
_AUDIO_UPLOAD_EXTENSIONS = frozenset({".ogg", ".oga", ".mp3", ".wav", ".m4a", ".aac", ".flac", ".webm"})


def _format_http_error_detail(body: dict) -> str:
    """Parse FastAPI error JSON (``detail`` string, list, or dict with code/message/hint)."""
    detail = body.get("detail")
    if isinstance(detail, dict):
        msg = detail.get("message") or detail.get("code") or "Request failed"
        hint = detail.get("hint")
        if hint:
            return f"{msg} — {hint}"
        return str(msg)
    if isinstance(detail, list):
        return str(detail)
    if isinstance(detail, str):
        return detail
    return str(body.get("detail", ""))


# Reflex handles one state event at a time. While ``send_message`` is an async
# generator, ``confirm_tool_decision`` cannot run. We pause the stream by
# returning from ``send_message`` and resume consumption in ``confirm_tool_decision``.
_chat_stream_queue: asyncio.Queue | None = None
_chat_stream_paused: bool = False


# ── models ──


class PendingFile(BaseModel):
    path: str = ""
    name: str = ""
    is_image: bool = False
    size_label: str = ""


class ChatMessage(BaseModel):
    role: str
    content: str
    thought: str = ""
    message_id: str = ""


def _dedupe_consecutive_identical_user_rows(msgs: list[ChatMessage]) -> list[ChatMessage]:
    """Collapse runs of consecutive user bubbles with the same text (storage/sync glitches).

    Legitimate repeat prompts are usually separated by an assistant turn; back-to-back
    duplicates are almost always accidental double-persistence.
    """
    out: list[ChatMessage] = []
    for m in msgs:
        if (
            m.role == "user"
            and out
            and out[-1].role == "user"
            and (m.content or "").strip() == (out[-1].content or "").strip()
        ):
            continue
        out.append(m)
    return out


def _build_messages_from_api_rows(raw: list[dict]) -> list[ChatMessage]:
    built = [
        ChatMessage(
            role=m["role"],
            content=m["content"],
            thought=str(m.get("thought") or ""),
            message_id=str(m.get("id") or ""),
        )
        for m in raw
        if m.get("role") in ("user", "assistant") and not message_hidden_from_chat_ui(m)
    ]
    seen: set[str] = set()
    unique: list[ChatMessage] = []
    for cm in built:
        mid = (cm.message_id or "").strip()
        if mid:
            if mid in seen:
                continue
            seen.add(mid)
        unique.append(cm)
    return _dedupe_consecutive_identical_user_rows(unique)


class EdgeToolEntry(BaseModel):
    name: str = ""
    full_name: str = ""
    description: str = ""
    disabled: bool = False
    require_confirmation: bool = False


class EdgeDeviceEntry(BaseModel):
    edge_name: str = ""
    online: bool = False
    tools: list[EdgeToolEntry] = []


class MonitorEdgeEntry(BaseModel):
    edge_name: str = ""
    online: bool = False
    tool_count: int = 0


class ToolTraceEntry(BaseModel):
    ts: str = ""
    display_name: str = ""
    tool_name: str = ""
    kind: str = ""
    status: str = ""
    duration_ms: int = 0
    session_id: str = ""
    args_summary: str = ""


# ────────────────────────────────────────────
#  State
# ────────────────────────────────────────────


class State(rx.State):
    messages: list[ChatMessage] = []
    draft: str = ""
    session_id: str = ""
    is_loading: bool = False
    error_message: str = ""
    upload_notice: str = ""
    streaming_content: str = ""
    streaming_thought: str = ""
    tool_messages: list[str] = []
    think_enabled: bool = False
    sessions: list[dict] = []
    pending_files: list[PendingFile] = []
    sidebar_visible: bool = True
    backend_url: str = ""
    current_page: str = "chat"
    rename_input: str = ""
    rename_dialog_open: bool = False
    dark_mode: bool = True
    session_search: str = ""

    # ── tools page state ──
    tools_data: dict = {}
    edge_devices_data: list[EdgeDeviceEntry] = []
    tools_search: str = ""

    # ── monitor page (topology + traces) ──
    monitor_edges_data: list[MonitorEdgeEntry] = []
    monitor_traces: list[ToolTraceEntry] = []
    trace_session_filter: str = ""

    # ── tool confirmation state ──
    confirm_dialog_open: bool = False
    confirm_call_id: str = ""
    confirm_tool_name: str = ""
    confirm_arguments: str = ""
    _confirm_pending: bool = False

    # ── settings page state ──
    model_config: dict = {}
    model_dialog_open: bool = False
    model_edit_chat_provider: str = ""
    model_edit_chat_model: str = ""
    model_edit_embed_provider: str = ""
    model_edit_embed_model: str = ""
    model_edit_openai_api_key: str = ""
    model_edit_gemini_api_key: str = ""
    model_edit_claude_api_key: str = ""
    model_edit_deepseek_api_key: str = ""
    model_edit_deepseek_base_url: str = ""
    model_edit_openai_base_url: str = ""
    model_saving: bool = False
    edit_memory_max_recent: int = 10
    edit_memory_max_related: int = 5
    memory_context_saving: bool = False

    default_prompt: str = ""
    default_prompt_is_default: bool = True
    prompt_draft: str = ""
    prompt_editing: bool = False

    session_prompt: str = ""
    session_prompt_custom: bool = False
    session_prompt_draft: str = ""
    session_prompt_editing: bool = False

    # ── computed ──

    @rx.var
    def has_pending_files(self) -> bool:
        return len(self.pending_files) > 0

    @rx.var
    def is_streaming(self) -> bool:
        return bool(self.streaming_content)

    @rx.var
    def has_thought(self) -> bool:
        return self.think_enabled and bool(self.streaming_thought)

    @rx.var
    def has_tool_messages(self) -> bool:
        return len(self.tool_messages) > 0

    @rx.var
    def current_title(self) -> str:
        for s in self.sessions:
            if s.get("session_id") == self.session_id:
                return s.get("title") or "New Chat"
        return "New Chat"

    @rx.var
    def show_empty(self) -> bool:
        return not self.messages and not self.streaming_content and not self.is_loading

    @rx.var
    def filtered_pinned(self) -> list[dict]:
        q = self.session_search.strip().lower()
        pinned = [s for s in self.sessions if s.get("is_pinned")]
        if not q:
            return pinned
        return [s for s in pinned if q in s.get("title", "").lower()]

    @rx.var
    def filtered_unpinned(self) -> list[dict]:
        q = self.session_search.strip().lower()
        unpinned = [s for s in self.sessions if not s.get("is_pinned")]
        if not q:
            return unpinned
        return [s for s in unpinned if q in s.get("title", "").lower()]

    @rx.var
    def has_filtered_pinned(self) -> bool:
        return len(self.filtered_pinned) > 0

    @rx.var
    def is_current_pinned(self) -> bool:
        return any(s.get("session_id") == self.session_id and s.get("is_pinned") for s in self.sessions)

    @rx.var
    def chat_textarea_disabled(self) -> bool:
        """While ``is_loading`` is true we pause the chat stream for tool confirmation without clearing it.

        In that case the textarea must stay editable so the user is not stuck; ``send_message`` still
        rejects a second send while ``is_loading`` is true.
        """
        if self.confirm_dialog_open:
            return False
        return self.is_loading

    @rx.var
    def server_tools(self) -> list[dict]:
        return self.tools_data.get("server_tools", [])

    @rx.var
    def edge_devices(self) -> list[EdgeDeviceEntry]:
        return self.edge_devices_data

    @rx.var
    def has_server_tools(self) -> bool:
        return len(self.tools_data.get("server_tools", [])) > 0

    @rx.var
    def has_edge_devices(self) -> bool:
        return len(self.edge_devices_data) > 0

    @rx.var
    def filtered_server_tools(self) -> list[dict]:
        q = self.tools_search.strip().lower()
        tools = self.tools_data.get("server_tools", [])
        if not q:
            return tools
        out: list[dict] = []
        for t in tools:
            blob = f"{t.get('name', '')} {t.get('description', '')}".lower()
            if q in blob:
                out.append(t)
        return out

    @rx.var
    def has_filtered_server_tools(self) -> bool:
        return len(self.filtered_server_tools) > 0

    @rx.var
    def filtered_edge_devices(self) -> list[EdgeDeviceEntry]:
        """Apply the same search string as server tools to edge tool names / full names / descriptions.

        If the query matches an edge device name, that device is listed with all of its tools.
        """
        q = self.tools_search.strip().lower()
        if not q:
            return self.edge_devices_data
        out: list[EdgeDeviceEntry] = []
        for dev in self.edge_devices_data:
            if q in (dev.edge_name or "").lower():
                out.append(dev)
                continue
            filtered_tools: list[EdgeToolEntry] = []
            for t in dev.tools:
                blob = f"{t.name} {t.full_name} {t.description}".lower()
                if q in blob:
                    filtered_tools.append(t)
            if filtered_tools:
                out.append(
                    EdgeDeviceEntry(
                        edge_name=dev.edge_name,
                        online=dev.online,
                        tools=filtered_tools,
                    )
                )
        return out

    @rx.var
    def has_filtered_edge_devices(self) -> bool:
        return len(self.filtered_edge_devices) > 0

    @rx.var
    def has_monitor_edges(self) -> bool:
        return len(self.monitor_edges_data) > 0

    @rx.var
    def has_monitor_traces(self) -> bool:
        return len(self.monitor_traces) > 0

    @rx.var
    def model_summary(self) -> str:
        p = self.model_config.get("chat_provider", "")
        m = self.model_config.get("chat_model", "")
        if p and m:
            return f"{p} / {m}"
        return "Not configured"

    @rx.var
    def session_prompt_display(self) -> str:
        if self.session_prompt_custom and self.session_prompt:
            return self.session_prompt
        return self.default_prompt

    @rx.var
    def embed_summary(self) -> str:
        p = self.model_config.get("embedding_provider", "")
        m = self.model_config.get("embedding_model", "")
        if p and m:
            return f"{p} / {m}"
        return "Not configured"

    @rx.var
    def memory_context_summary(self) -> str:
        r = self.model_config.get("memory_max_recent_messages", 10)
        rel = self.model_config.get("memory_max_related_messages", 5)
        return f"Last {r} in session · {rel} cross-session related"

    @rx.var
    def model_openai_key_saved(self) -> bool:
        return bool(self.model_config.get("openai_api_key_saved"))

    @rx.var
    def model_gemini_key_saved(self) -> bool:
        return bool(self.model_config.get("gemini_api_key_saved"))

    @rx.var
    def model_claude_key_saved(self) -> bool:
        return bool(self.model_config.get("claude_api_key_saved"))

    @rx.var
    def model_deepseek_key_saved(self) -> bool:
        return bool(self.model_config.get("deepseek_api_key_saved"))

    # ── private helpers ──

    def _base_url(self) -> str:
        return os.getenv("YUMI_SERVER_URL", DEFAULT_SERVER_URL).rstrip("/")

    def _api(self, path: str) -> str:
        return f"{self._base_url()}{path}"

    def _chat_endpoint(self) -> str:
        return f"{self._base_url()}/chat"

    def _headers(self) -> dict:
        return {"Content-Type": "application/json"}

    def _fetch_sessions(self):
        try:
            r = requests.get(
                self._api("/memory/sessions?status=active"),
                headers=self._headers(),
                timeout=5,
            )
            if r.ok:
                data = r.json().get("sessions", [])
                for s in data:
                    if not s.get("title"):
                        s["title"] = "New Chat"
                self.sessions = data
        except Exception:
            self.sessions = []

    def _fetch_messages(self):
        if not self.session_id:
            return
        try:
            r = requests.get(
                self._api(f"/memory/messages?session_id={self.session_id}&limit=200"),
                headers=self._headers(),
                timeout=5,
            )
            if r.ok:
                raw = r.json().get("messages", [])
                self.messages = _build_messages_from_api_rows(raw)
        except Exception:
            self.messages = []

    def _make_session(self):
        try:
            r = requests.post(
                self._api("/memory/sessions"),
                json={},
                headers=self._headers(),
                timeout=5,
            )
            if r.ok:
                s = r.json().get("session", {})
                self.session_id = s.get("session_id", "")
                self._fetch_sessions()
                self.messages = []
                return
        except Exception:
            pass
        self.session_id = f"ui_{uuid.uuid4().hex[:12]}"
        self.messages = []

    def _reset_chat_ui(self):
        self.draft = ""
        self.error_message = ""
        self.upload_notice = ""
        self.streaming_content = ""
        self.streaming_thought = ""
        self.tool_messages = []
        self.pending_files = []

    # ── event handlers ──

    def initialize(self):
        self.current_page = "chat"
        if not self.backend_url:
            self.backend_url = self._base_url()
        self._fetch_dark_mode()
        self._fetch_sessions()
        # Do not short-circuit when ``session_id`` is already set (Reflex client persistence).
        # The previous early return skipped ``start_timer_listener``, so ``/timer-events`` was never
        # consumed and timer completions never reached the chat UI.
        if self.session_id:
            self._fetch_messages()
        elif self.sessions:
            self.session_id = self.sessions[0].get("session_id", "")
            self._fetch_messages()
        else:
            self._make_session()

        start_timer_listener(self._base_url(), self._headers())
        return rx.call_script(_TIMER_POLL_JS, callback=State.poll_timer_events)

    def init_settings(self):
        self.current_page = "settings"
        if not self.backend_url:
            self.backend_url = self._base_url()
        self._fetch_dark_mode()
        self._fetch_model_config()
        self._fetch_default_prompt()
        self._fetch_session_prompt()

    def init_tools(self):
        self.current_page = "tools"
        if not self.backend_url:
            self.backend_url = self._base_url()
        self._fetch_dark_mode()
        self._fetch_tools()

    def init_monitor(self):
        self.current_page = "monitor"
        if not self.backend_url:
            self.backend_url = self._base_url()
        self._fetch_dark_mode()
        self._fetch_monitor_topology()
        self._fetch_monitor_traces()
        return rx.call_script(_MONITOR_POLL_JS, callback=State.poll_monitor_tick)

    def poll_monitor_tick(self, _tick: str = ""):
        if self.current_page != "monitor":
            return
        self._fetch_monitor_topology()
        self._fetch_monitor_traces()
        return rx.call_script(_MONITOR_POLL_JS, callback=State.poll_monitor_tick)

    def set_tools_search(self, value: str):
        self.tools_search = value

    def set_trace_session_filter(self, value: str):
        self.trace_session_filter = value

    def refresh_monitor(self):
        self._fetch_monitor_topology()
        self._fetch_monitor_traces()

    def apply_trace_session_filter(self):
        self._fetch_monitor_traces()

    def export_monitor_traces(self):
        try:
            params: dict[str, Any] = {}
            if self.trace_session_filter.strip():
                params["session_id"] = self.trace_session_filter.strip()
            r = requests.get(
                self._api("/monitor/traces/export"),
                params=params,
                headers=self._headers(),
                timeout=120,
            )
            if not r.ok:
                return
            return rx.download(data=r.content, filename="yumi_tool_traces.ndjson")
        except Exception:
            pass

    def new_chat(self):
        self._reset_chat_ui()
        self._make_session()
        if self.current_page == "settings":
            self.session_prompt_editing = False
            self.session_prompt_custom = False
            self.session_prompt = ""
            self.session_prompt_draft = self.default_prompt

    def select_session(self, session_id: str):
        if session_id == self.session_id:
            return
        self.session_id = session_id
        self._reset_chat_ui()
        self._fetch_messages()
        if self.current_page == "settings":
            self.session_prompt_editing = False
            self._fetch_session_prompt()

    def delete_session(self, session_id: str):
        try:
            requests.put(
                self._api(f"/memory/sessions/{session_id}"),
                json={"status": "deleted"},
                headers=self._headers(),
                timeout=5,
            )
        except Exception:
            pass
        need_switch = session_id == self.session_id
        self._fetch_sessions()
        if need_switch:
            if self.sessions:
                self.session_id = self.sessions[0].get("session_id", "")
                self._fetch_messages()
            else:
                self._make_session()

    def toggle_pin_current(self):
        is_pinned = self.is_current_pinned
        try:
            requests.put(
                self._api(f"/memory/sessions/{self.session_id}"),
                json={"is_pinned": not is_pinned},
                headers=self._headers(),
                timeout=5,
            )
        except Exception:
            pass
        self._fetch_sessions()

    def handle_rename_dialog(self, is_open: bool):
        self.rename_dialog_open = is_open
        if is_open:
            for s in self.sessions:
                if s.get("session_id") == self.session_id:
                    t = s.get("title", "")
                    self.rename_input = t if t != "New Chat" else ""
                    break
            else:
                self.rename_input = ""
            return rx.call_script(
                "setTimeout(function(){"
                "var el=document.getElementById('rename-input');"
                f"if(el){{el.value={json.dumps(self.rename_input)};el.focus();"
                "var c=false;"
                "el.addEventListener('compositionstart',function(){c=true});"
                "el.addEventListener('compositionend',function(){c=false});"
                "el.addEventListener('keydown',function(e){"
                "if(e.key==='Enter'&&!c&&!e.isComposing){"
                "e.preventDefault();"
                "var btn=document.querySelector('[data-rename-save]');"
                "if(btn)btn.click();"
                "}"
                "});"
                "}},50)"
            )

    def rename_session(self):
        title = self.rename_input.strip()
        if not title:
            self.rename_dialog_open = False
            return
        try:
            requests.put(
                self._api(f"/memory/sessions/{self.session_id}"),
                json={"title": title},
                headers=self._headers(),
                timeout=5,
            )
        except Exception:
            pass
        self.rename_dialog_open = False
        self._fetch_sessions()

    def set_draft(self, value: str):
        self.draft = value

    def toggle_think(self):
        self.think_enabled = not self.think_enabled

    async def handle_chat_file_upload(self, files: list[rx.UploadFile]):
        """Send selected files to ``POST /uploads`` and append paths to the draft for the model."""
        if not files:
            return
        if not self.session_id:
            self._make_session()
        if not self.session_id:
            self.error_message = "Could not create a session. Try uploading again in a moment."
            self.upload_notice = ""
            return

        def _post_upload(filename: str, b64: str) -> tuple[bool, str, str, bool]:
            try:
                r = requests.post(
                    self._api("/uploads"),
                    json={
                        "session_id": self.session_id,
                        "filename": filename,
                        "content_base64": b64,
                    },
                    headers=self._headers(),
                    timeout=120,
                )
                try:
                    body = r.json()
                except Exception:
                    body = {}
                if not r.ok:
                    if isinstance(body, dict):
                        detail = _format_http_error_detail(body) or r.text or str(r.status_code)
                    else:
                        detail = r.text or str(r.status_code)
                    return False, "", str(detail), False
                path = body.get("path", "") if isinstance(body, dict) else ""
                is_image = bool(body.get("is_image", False)) if isinstance(body, dict) else False
                return True, path, "", is_image
            except Exception as exc:
                return False, "", str(exc), False

        def _post_audio_transcribe(filename: str, b64: str) -> tuple[bool, str, str]:
            try:
                r = requests.post(
                    self._api("/stt/transcribe"),
                    json={
                        "session_id": self.session_id,
                        "filename": filename,
                        "content_base64": b64,
                    },
                    headers=self._headers(),
                    timeout=600,
                )
                try:
                    body = r.json()
                except Exception:
                    body = {}
                if not r.ok:
                    detail = _format_http_error_detail(body) if isinstance(body, dict) else ""
                    return False, "", detail or r.text or str(r.status_code)
                return True, str(body.get("text") or "").strip(), ""
            except Exception as exc:
                return False, "", str(exc)

        saved_paths: list[str] = []
        image_paths: list[str] = []
        doc_paths: list[str] = []
        transcribed_audio: list[str] = []
        for uf in files:
            try:
                raw = await uf.read()
            except Exception as exc:
                self.error_message = f"Failed to read local file: {exc}"
                self.upload_notice = ""
                return
            if len(raw) > _MAX_CHAT_UPLOAD_BYTES:
                self.error_message = f"File too large (max {_MAX_CHAT_UPLOAD_BYTES // (1024 * 1024)} MB)."
                self.upload_notice = ""
                return
            name = uf.filename or "upload.bin"
            b64 = base64.standard_b64encode(raw).decode("ascii")
            if Path(name).suffix.lower() in _AUDIO_UPLOAD_EXTENSIONS:
                ok_t, text, err_t = await asyncio.to_thread(_post_audio_transcribe, name, b64)
                if not ok_t:
                    self.error_message = f"Audio transcription failed: {err_t}"
                    self.upload_notice = ""
                    return
                if text:
                    transcribed_audio.append(text)
                continue
            ok, path, err, is_image = await asyncio.to_thread(_post_upload, name, b64)
            if not ok:
                self.error_message = f"Upload failed: {err}"
                self.upload_notice = ""
                return
            if path:
                saved_paths.append(path)
                if is_image:
                    image_paths.append(path)
                else:
                    doc_paths.append(path)

        if transcribed_audio:
            merged = "\n\n".join(transcribed_audio)
            self.draft = f"{self.draft.rstrip()}\n\n{merged}".strip() if self.draft.strip() else merged

        if not saved_paths:
            if transcribed_audio:
                self.error_message = ""
                self.upload_notice = "Audio transcribed into the message draft."
                yield rx.call_script(CHAT_INPUT_RESIZE_FOCUS_JS)
                yield rx.clear_selected_files("yumi_chat_upload")
                yield rx.clear_selected_files("yumi_chat_drop")
                return
            self.error_message = "Upload did not return a file path."
            self.upload_notice = ""
            return

        self.error_message = ""
        self.upload_notice = "Audio transcribed into the draft." if transcribed_audio else ""

        new_files: list[PendingFile] = []
        for p, is_img in zip(saved_paths, [p in image_paths for p in saved_paths]):
            name = Path(p).name
            try:
                size = Path(p).stat().st_size
                if size < 1024:
                    sl = f"{size} B"
                elif size < 1024 * 1024:
                    sl = f"{size / 1024:.0f} KB"
                else:
                    sl = f"{size / (1024 * 1024):.1f} MB"
            except Exception:
                sl = ""
            new_files.append(PendingFile(path=p, name=name, is_image=is_img, size_label=sl))

        self.pending_files = [*self.pending_files, *new_files]
        yield rx.call_script(CHAT_INPUT_RESIZE_FOCUS_JS)
        yield rx.clear_selected_files("yumi_chat_upload")
        yield rx.clear_selected_files("yumi_chat_drop")

    def remove_pending_file(self, path: str):
        self.pending_files = [f for f in self.pending_files if f.path != path]

    def clear_pending_files(self):
        self.pending_files = []

    def set_rename_input(self, value: str):
        self.rename_input = value

    def set_session_search(self, value: str):
        self.session_search = value

    def toggle_sidebar(self):
        self.sidebar_visible = not self.sidebar_visible

    def toggle_dark_mode(self):
        self.dark_mode = not self.dark_mode
        self._save_dark_mode()

    def set_dark(self):
        self.dark_mode = True
        self._save_dark_mode()

    def set_light(self):
        self.dark_mode = False
        self._save_dark_mode()

    def _fetch_dark_mode(self):
        try:
            r = requests.get(self._api("/config/ui"), headers=self._headers(), timeout=3)
            if r.ok:
                self.dark_mode = r.json().get("dark_mode", True)
        except Exception:
            pass

    def _save_dark_mode(self):
        try:
            requests.put(
                self._api("/config/ui"),
                json={"dark_mode": self.dark_mode},
                headers=self._headers(),
                timeout=3,
            )
        except Exception:
            pass

    # ── explicit setters (avoid auto-setter deprecation) ──

    def set_prompt_draft(self, value: str):
        self.prompt_draft = value

    def set_session_prompt_draft(self, value: str):
        self.session_prompt_draft = value

    def set_model_edit_chat_provider(self, value: str):
        self.model_edit_chat_provider = value

    def set_model_edit_chat_model(self, value: str):
        self.model_edit_chat_model = value

    def set_model_edit_embed_provider(self, value: str):
        self.model_edit_embed_provider = value

    def set_model_edit_embed_model(self, value: str):
        self.model_edit_embed_model = value

    def set_model_edit_openai_api_key(self, value: str):
        self.model_edit_openai_api_key = value

    def set_model_edit_gemini_api_key(self, value: str):
        self.model_edit_gemini_api_key = value

    def set_model_edit_claude_api_key(self, value: str):
        self.model_edit_claude_api_key = value

    def set_model_edit_openai_base_url(self, value: str):
        self.model_edit_openai_base_url = value

    def set_model_edit_deepseek_api_key(self, value: str):
        self.model_edit_deepseek_api_key = value

    def set_model_edit_deepseek_base_url(self, value: str):
        self.model_edit_deepseek_base_url = value

    def use_suggestion(self, text: str):
        self.draft = text
        return rx.call_script(CHAT_INPUT_RESIZE_FOCUS_JS)

    def copy_text(self, text: str):
        return rx.call_script(f"navigator.clipboard.writeText({json.dumps(text)})")

    # ── tools event handlers ──

    def _fetch_tools(self):
        try:
            r = requests.get(self._api("/tools"), headers=self._headers(), timeout=5)
            if not r.ok:
                logger.warning("Tools fetch failed: HTTP %s", r.status_code)
                return
            raw = r.json()
            self.tools_data = raw

            edge_raw = raw.get("edge_devices") or raw.get("edge", [])
            devices = []
            for dev in edge_raw:
                tools = []
                for t in dev.get("tools", []):
                    raw_name = t.get("name", "")
                    full = t.get("full_name", raw_name)
                    display = full.split("__", 1)[1] if "__" in full else raw_name
                    tools.append(
                        EdgeToolEntry(
                            name=display,
                            full_name=full,
                            description=t.get("description", ""),
                            disabled=t.get("disabled", False),
                            require_confirmation=t.get("require_confirmation", False),
                        )
                    )
                devices.append(
                    EdgeDeviceEntry(
                        edge_name=dev.get("edge_name", ""),
                        online=dev.get("online", False),
                        tools=tools,
                    )
                )
            self.edge_devices_data = devices
        except Exception as exc:
            logger.warning("Error fetching tools: %s", exc)
            self.tools_data = {}
            self.edge_devices_data = []

    def _fetch_monitor_topology(self):
        try:
            r = requests.get(self._api("/monitor/topology"), headers=self._headers(), timeout=5)
            if not r.ok:
                return
            data = r.json()
            edges: list[MonitorEdgeEntry] = []
            for e in data.get("edges", []):
                edges.append(
                    MonitorEdgeEntry(
                        edge_name=str(e.get("edge_name", "")),
                        online=bool(e.get("online")),
                        tool_count=int(e.get("tool_count", 0)),
                    )
                )
            self.monitor_edges_data = edges
        except Exception:
            self.monitor_edges_data = []

    def _fetch_monitor_traces(self):
        try:
            params: dict[str, Any] = {"limit": "200"}
            if self.trace_session_filter.strip():
                params["session_id"] = self.trace_session_filter.strip()
            r = requests.get(
                self._api("/monitor/traces"),
                params=params,
                headers=self._headers(),
                timeout=15,
            )
            if not r.ok:
                return
            raw = r.json().get("traces", [])
            norm: list[ToolTraceEntry] = []
            for t in raw:
                args = t.get("arguments")
                try:
                    s = json.dumps(args, ensure_ascii=False, default=str)
                except (TypeError, ValueError):
                    s = str(args)
                if len(s) > 120:
                    s = s[:117] + "..."
                ts = str(t.get("ts", ""))
                short_ts = ts.replace("T", " ")[:19] if ts else ""
                norm.append(
                    ToolTraceEntry(
                        ts=short_ts or ts,
                        display_name=str(t.get("display_name") or t.get("tool_name", "")),
                        tool_name=str(t.get("tool_name", "")),
                        kind=str(t.get("kind", "")),
                        status=str(t.get("status", "")),
                        duration_ms=int(t.get("duration_ms") or 0),
                        session_id=str(t.get("session_id", "")),
                        args_summary=s,
                    )
                )
            self.monitor_traces = norm
        except Exception:
            self.monitor_traces = []

    def toggle_tool(self, tool_name: str):
        try:
            disabled_list = self.tools_data.get("disabled_tools", [])
            is_disabled = tool_name in disabled_list
            requests.post(
                self._api("/tools/toggle"),
                json={"tool_name": tool_name, "disabled": not is_disabled},
                headers=self._headers(),
                timeout=5,
            )
            self._fetch_tools()
        except Exception:
            pass

    def toggle_confirmation(self, tool_name: str, currently_effective: bool):
        """Flip effective confirmation for this tool (matches Tools page shield state)."""
        try:
            requests.post(
                self._api("/tools/set-confirmation"),
                json={
                    "tool_name": tool_name,
                    "require_confirmation": not currently_effective,
                },
                headers=self._headers(),
                timeout=5,
            )
            self._fetch_tools()
        except Exception:
            pass

    def _show_confirmation_dialog(self, call_id: str, tool_name: str, arguments: dict):
        self.confirm_dialog_open = True
        self.confirm_call_id = call_id
        self.confirm_tool_name = tool_name
        self.confirm_arguments = json.dumps(arguments, ensure_ascii=False, indent=2)

    async def confirm_tool_decision(self, decision: str):
        global _chat_stream_queue, _chat_stream_paused
        if not self.confirm_call_id:
            return
        call_id = self.confirm_call_id
        try:
            await asyncio.to_thread(
                lambda: requests.post(
                    self._api("/tools/confirm"),
                    json={"call_id": call_id, "decision": decision},
                    headers=self._headers(),
                    timeout=5,
                ),
            )
        except Exception:
            pass
        self.confirm_dialog_open = False
        self._confirm_pending = False
        self.confirm_call_id = ""
        self.confirm_tool_name = ""
        self.confirm_arguments = ""
        if decision == "always_allow":
            await asyncio.to_thread(self._fetch_tools)

        q = _chat_stream_queue
        if q is not None and _chat_stream_paused:
            _chat_stream_paused = False
            async for update in self._drive_chat_stream(q, resume=True):
                yield update
        else:
            self.is_loading = False

    async def _finalize_successful_chat_turn(self):
        self.streaming_content = ""
        self.streaming_thought = ""
        self.tool_messages = []
        await asyncio.to_thread(self._fetch_sessions)
        # Single source of truth: server memory already has user + assistant rows after the
        # stream ends; reloading avoids duplicate user bubbles (optimistic local + DB rows).
        await asyncio.to_thread(self._fetch_messages)

    async def _drive_chat_stream(self, chat_q: asyncio.Queue, *, resume: bool = False):
        global _chat_stream_queue, _chat_stream_paused
        if not resume:
            _chat_stream_queue = chat_q
            _chat_stream_paused = False
        try:
            while True:
                item = await chat_q.get()
                if item is None:
                    await self._finalize_successful_chat_turn()
                    _chat_stream_queue = None
                    _chat_stream_paused = False
                    self.is_loading = False
                    return
                if isinstance(item, Exception):
                    raise item
                line = item
                try:
                    evt = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = evt.get("type")

                if t == "text":
                    self.streaming_content += evt.get("content", "")
                    yield
                elif t == "thought":
                    if self.think_enabled:
                        self.streaming_thought += evt.get("content", "")
                    yield
                elif t == "tool_confirmation":
                    self._confirm_pending = True
                    self.confirm_call_id = evt.get("call_id", "")
                    self.confirm_tool_name = evt.get("tool_name", "")
                    self.confirm_arguments = json.dumps(
                        evt.get("arguments", {}),
                        ensure_ascii=False,
                        indent=2,
                    )
                    self.confirm_dialog_open = True
                    self.tool_messages = [
                        *self.tool_messages,
                        f"🛡️ Waiting for confirmation: '{evt.get('tool_name', '')}'",
                    ]
                    yield
                    _chat_stream_paused = True
                    return
                elif t == "tool_status":
                    st = evt.get("status", "")
                    ct = evt.get("content", "")
                    icons = {"running": "⚙️", "success": "✅", "error": "❌"}
                    self.tool_messages = [
                        *self.tool_messages,
                        f"{icons.get(st, 'ℹ️')} {ct}",
                    ]
                    yield
                elif t == "error":
                    raise RuntimeError(evt.get("content", "Unknown error"))
        except Exception as exc:
            self.error_message = str(exc)
            partial = self.streaming_content.strip()
            if partial:
                thought_saved = self.streaming_thought.strip() if self.think_enabled else ""
                self.messages.append(
                    ChatMessage(
                        role="assistant",
                        content=partial,
                        thought=thought_saved,
                    )
                )
            self.streaming_content = ""
            self.streaming_thought = ""
            self.tool_messages = []
            _chat_stream_queue = None
            _chat_stream_paused = False
            self.is_loading = False

    # ── settings handlers ──

    def _fetch_model_config(self):
        try:
            r = requests.get(self._api("/config/model"), headers=self._headers(), timeout=5)
            if r.ok:
                self.model_config = r.json()
                self._sync_memory_context_edits()
        except Exception:
            self.model_config = {}

    def _sync_memory_context_edits(self):
        try:
            self.edit_memory_max_recent = max(
                1,
                min(500, int(self.model_config.get("memory_max_recent_messages", 10))),
            )
        except (TypeError, ValueError):
            self.edit_memory_max_recent = 10
        try:
            self.edit_memory_max_related = max(
                0,
                min(100, int(self.model_config.get("memory_max_related_messages", 5))),
            )
        except (TypeError, ValueError):
            self.edit_memory_max_related = 5

    def set_edit_memory_max_recent(self, v: float):
        try:
            n = int(round(v))
            self.edit_memory_max_recent = max(1, min(500, n))
        except (ValueError, TypeError, OverflowError):
            pass

    def set_edit_memory_max_related(self, v: float):
        try:
            n = int(round(v))
            self.edit_memory_max_related = max(0, min(100, n))
        except (ValueError, TypeError, OverflowError):
            pass

    def _fetch_default_prompt(self):
        try:
            r = requests.get(self._api("/config/system-prompt"), headers=self._headers(), timeout=5)
            if r.ok:
                data = r.json()
                self.default_prompt = data.get("system_prompt", "")
                self.default_prompt_is_default = data.get("is_default", True)
                self.prompt_draft = self.default_prompt
        except Exception:
            pass

    def _fetch_session_prompt(self):
        if not self.session_id:
            return
        try:
            r = requests.get(
                self._api(f"/config/session-prompt/{self.session_id}"),
                headers=self._headers(),
                timeout=5,
            )
            if r.ok:
                data = r.json()
                self.session_prompt_custom = data.get("is_custom", False)
                self.session_prompt = data.get("system_prompt") or ""
                self.session_prompt_draft = self.session_prompt
        except Exception:
            pass

    def open_model_dialog(self):
        self.model_edit_chat_provider = self.model_config.get("chat_provider", "ollama")
        self.model_edit_chat_model = self.model_config.get("chat_model", "")
        self.model_edit_embed_provider = self.model_config.get("embedding_provider", "ollama")
        self.model_edit_embed_model = self.model_config.get("embedding_model", "")
        self.model_edit_openai_api_key = ""
        self.model_edit_gemini_api_key = ""
        self.model_edit_claude_api_key = ""
        self.model_edit_deepseek_api_key = ""
        self.model_edit_deepseek_base_url = self.model_config.get("deepseek_base_url") or ""
        self.model_edit_openai_base_url = self.model_config.get("openai_base_url") or ""
        self.model_dialog_open = True
        return rx.call_script(
            "setTimeout(function(){"
            f"var a=document.getElementById('edit-chat-model');if(a)a.value={json.dumps(self.model_edit_chat_model)};"
            f"var b=document.getElementById('edit-embed-model');if(b)b.value={json.dumps(self.model_edit_embed_model)};"
            "},50)"
        )

    def close_model_dialog(self):
        self.model_dialog_open = False

    def handle_model_dialog(self, is_open: bool):
        self.model_dialog_open = is_open

    async def save_model_config(self):
        self.model_saving = True
        yield
        try:

            def _put_model_config():
                payload = {
                    "chat_provider": self.model_edit_chat_provider,
                    "chat_model": self.model_edit_chat_model,
                    "embedding_provider": self.model_edit_embed_provider,
                    "embedding_model": self.model_edit_embed_model,
                    "openai_base_url": self.model_edit_openai_base_url,
                    "deepseek_base_url": self.model_edit_deepseek_base_url,
                }
                if self.model_edit_openai_api_key.strip():
                    payload["openai_api_key"] = self.model_edit_openai_api_key.strip()
                if self.model_edit_gemini_api_key.strip():
                    payload["gemini_api_key"] = self.model_edit_gemini_api_key.strip()
                if self.model_edit_claude_api_key.strip():
                    payload["claude_api_key"] = self.model_edit_claude_api_key.strip()
                if self.model_edit_deepseek_api_key.strip():
                    payload["deepseek_api_key"] = self.model_edit_deepseek_api_key.strip()
                return requests.put(
                    self._api("/config/model"),
                    json=payload,
                    headers=self._headers(),
                    timeout=30,
                )

            r = await asyncio.to_thread(_put_model_config)
            if r.ok:
                data = r.json()
                self.model_config = {k: v for k, v in data.items() if k != "status"}
                self.model_edit_openai_api_key = ""
                self.model_edit_gemini_api_key = ""
                self.model_edit_claude_api_key = ""
                self.model_edit_deepseek_api_key = ""
                self.model_dialog_open = False
            else:
                try:
                    self.error_message = _format_http_error_detail(r.json()) or "Failed to update model"
                except Exception:
                    self.error_message = r.text or "Failed to update model"
        except Exception as exc:
            self.error_message = str(exc)
        finally:
            self.model_saving = False

    async def save_memory_context(self):
        self.memory_context_saving = True
        yield
        try:
            r = await asyncio.to_thread(
                lambda: requests.put(
                    self._api("/config/model"),
                    json={
                        "memory_max_recent_messages": self.edit_memory_max_recent,
                        "memory_max_related_messages": self.edit_memory_max_related,
                    },
                    headers=self._headers(),
                    timeout=15,
                ),
            )
            if r.ok:
                data = r.json()
                self.model_config = {k: v for k, v in data.items() if k != "status"}
                self._sync_memory_context_edits()
            else:
                try:
                    self.error_message = _format_http_error_detail(r.json()) or "Save failed"
                except Exception:
                    self.error_message = "Save failed"
        except Exception as exc:
            self.error_message = str(exc)
        finally:
            self.memory_context_saving = False

    def start_edit_prompt(self):
        self.prompt_editing = True
        self.prompt_draft = self.default_prompt
        return rx.call_script(
            "setTimeout(function(){var el=document.getElementById('edit-default-prompt');"
            f"if(el)el.value={json.dumps(self.prompt_draft)}}},50)"
        )

    def cancel_edit_prompt(self):
        self.prompt_editing = False
        self.prompt_draft = self.default_prompt

    def save_default_prompt(self):
        try:
            r = requests.put(
                self._api("/config/system-prompt"),
                json={"system_prompt": self.prompt_draft},
                headers=self._headers(),
                timeout=5,
            )
            if r.ok:
                self.default_prompt = self.prompt_draft
                self.default_prompt_is_default = False
                self.prompt_editing = False
        except Exception:
            pass

    def reset_default_prompt(self):
        try:
            r = requests.delete(self._api("/config/system-prompt"), headers=self._headers(), timeout=5)
            if r.ok:
                data = r.json()
                self.default_prompt = data.get("system_prompt", "")
                self.default_prompt_is_default = True
                self.prompt_draft = self.default_prompt
                self.prompt_editing = False
        except Exception:
            pass

    def start_edit_session_prompt(self):
        self.session_prompt_editing = True
        if self.session_prompt_custom:
            self.session_prompt_draft = self.session_prompt
        else:
            self.session_prompt_draft = self.default_prompt
        return rx.call_script(
            "setTimeout(function(){var el=document.getElementById('edit-session-prompt');"
            f"if(el)el.value={json.dumps(self.session_prompt_draft)}}},50)"
        )

    def cancel_edit_session_prompt(self):
        self.session_prompt_editing = False

    def save_session_prompt(self):
        if not self.session_id:
            return
        try:
            r = requests.put(
                self._api(f"/config/session-prompt/{self.session_id}"),
                json={"system_prompt": self.session_prompt_draft},
                headers=self._headers(),
                timeout=5,
            )
            if r.ok:
                self.session_prompt = self.session_prompt_draft
                self.session_prompt_custom = True
                self.session_prompt_editing = False
        except Exception:
            pass

    def reset_session_prompt(self):
        if not self.session_id:
            return
        try:
            r = requests.delete(
                self._api(f"/config/session-prompt/{self.session_id}"),
                headers=self._headers(),
                timeout=5,
            )
            if r.ok:
                self.session_prompt = ""
                self.session_prompt_custom = False
                self.session_prompt_editing = False
                self.session_prompt_draft = self.default_prompt
        except Exception:
            pass

    async def send_message(self):
        global _chat_stream_paused
        prompt = self.draft.strip()
        if not prompt and not self.pending_files:
            return
        if self.is_loading:
            return

        file_prefix = ""
        if self.pending_files:
            img = [f.path for f in self.pending_files if f.is_image]
            doc = [f.path for f in self.pending_files if not f.is_image]
            parts: list[str] = []
            if img:
                parts.append(
                    "The following images are saved on the Yumi server and will be inlined for the vision model. "
                    "Please view them and describe what you see:\n" + "\n".join(img)
                )
            if doc:
                parts.append(
                    "The following files are saved on the Yumi server. Use the read_file tool to read each path "
                    "in order and answer the user's question:\n" + "\n".join(doc)
                )
            file_prefix = "\n\n".join(parts)
            self.pending_files = []

        display_text = prompt or "Please analyze the uploaded file(s)"
        actual_prompt = f"{file_prefix}\n\n{prompt}".strip() if file_prefix else prompt

        self.messages.append(ChatMessage(role="user", content=display_text))
        self.draft = ""
        self.error_message = ""
        self.upload_notice = ""
        self.is_loading = True
        self.streaming_content = ""
        self.streaming_thought = ""
        self.tool_messages = []
        yield rx.call_script(CHAT_INPUT_RESET_HEIGHT_JS)

        loop = asyncio.get_running_loop()
        chat_q: asyncio.Queue = asyncio.Queue()

        def _enqueue(item: object) -> None:
            fut = asyncio.run_coroutine_threadsafe(chat_q.put(item), loop)
            fut.result()

        def _ndjson_reader() -> None:
            try:
                with requests.post(
                    self._chat_endpoint(),
                    json={
                        "prompt": actual_prompt,
                        "session_id": self.session_id,
                        "think": self.think_enabled,
                    },
                    headers=self._headers(),
                    stream=True,
                    timeout=(10, 300),
                ) as resp:
                    if not resp.ok:
                        try:
                            d = _format_http_error_detail(resp.json())
                        except Exception:
                            d = ""
                        _enqueue(RuntimeError(d or f"{resp.status_code} {resp.reason}"))
                        return
                    for line in resp.iter_lines(decode_unicode=True):
                        if line:
                            _enqueue(line)
            except Exception as exc:
                _enqueue(exc)
            finally:
                _enqueue(None)

        threading.Thread(target=_ndjson_reader, daemon=True).start()

        try:
            async for update in self._drive_chat_stream(chat_q, resume=False):
                yield update
        finally:
            if not _chat_stream_paused:
                self.is_loading = False

    def poll_timer_events(self, _js_result: str = ""):
        batch: list[dict] = []
        while not timer_event_queue.empty():
            try:
                batch.append(timer_event_queue.get_nowait())
            except queue.Empty:
                break

        for payload in batch:
            session_id = payload.get("session_id", "")
            events = payload.get("events", [])
            description = payload.get("description", "")

            if session_id != self.session_id:
                continue

            text_parts = []
            thought_parts = []
            error_parts = []
            for evt in events:
                t = evt.get("type")
                if t == "text":
                    text_parts.append(evt.get("content", ""))
                elif t == "thought":
                    thought_parts.append(evt.get("content", ""))
                elif t == "error":
                    error_parts.append(evt.get("content", ""))

            assistant_text = "".join(text_parts).strip()
            thought_text = "".join(thought_parts).strip()

            if not assistant_text and error_parts:
                assistant_text = f"(Timer error: {'; '.join(error_parts)})"
            if not assistant_text:
                assistant_text = f"⏰ [Timer: {description}]"

            display = f"⏰ {assistant_text}" if not assistant_text.startswith("⏰") else assistant_text
            self.messages = [
                *self.messages,
                ChatMessage(
                    role="assistant",
                    content=display,
                    thought=thought_text if self.think_enabled else "",
                ),
            ]

        if self.current_page == "chat":
            return rx.call_script(_TIMER_POLL_JS, callback=State.poll_timer_events)


# ────────────────────────────────────────────
#  Sidebar
# ────────────────────────────────────────────


def _session_item(session) -> rx.Component:
    active = session["session_id"] == State.session_id
    return rx.hstack(
        rx.cond(
            session["is_pinned"],
            rx.icon("pin", size=14, color=rx.cond(active, ACCENT, SB_TEXT), flex_shrink="0"),
            rx.icon("message-square", size=14, color=rx.cond(active, SB_TEXT_HI, SB_TEXT), flex_shrink="0"),
        ),
        rx.text(
            session["title"],
            size="2",
            weight=rx.cond(active, "medium", "regular"),
            color=rx.cond(active, SB_TEXT_HI, SB_TEXT),
            overflow="hidden",
            text_overflow="ellipsis",
            white_space="nowrap",
            flex="1",
            min_width="0",
        ),
        on_click=State.select_session(session["session_id"]),
        padding_x="12px",
        padding_y="7px",
        border_radius="8px",
        cursor="pointer",
        width="100%",
        overflow="hidden",
        align="center",
        spacing="2",
        background=rx.cond(active, SB_HOVER, "transparent"),
        _hover={"background": SB_HOVER},
        transition="background 0.12s",
    )


def _section_label(text: str) -> rx.Component:
    return rx.text(
        text,
        size="1",
        weight="medium",
        color="#475569",
        letter_spacing="0.05em",
        padding_x="12px",
        padding_top="10px",
        padding_bottom="3px",
    )


def _nav_link(icon_name: str, label: str, href: str, page_key: str) -> rx.Component:
    active = State.current_page == page_key
    return rx.link(
        rx.hstack(
            rx.icon(icon_name, size=15, color=rx.cond(active, SB_TEXT_HI, SB_TEXT)),
            rx.text(
                label, size="2", color=rx.cond(active, SB_TEXT_HI, SB_TEXT), weight=rx.cond(active, "medium", "regular")
            ),
            spacing="2",
            align="center",
            width="100%",
            padding="7px 10px",
            border_radius="7px",
            background=rx.cond(active, SB_HOVER, "transparent"),
            _hover={"background": SB_HOVER},
            transition="background 0.12s",
        ),
        href=href,
        underline="none",
        width="100%",
    )


def sidebar() -> rx.Component:
    return rx.vstack(
        # ── brand ──
        rx.hstack(
            rx.icon("sparkles", size=16, color=ACCENT),
            rx.heading("Yumi", size="3", weight="bold", color="white", letter_spacing="-0.02em"),
            spacing="2",
            align="center",
            padding_x="16px",
            padding_top="16px",
            padding_bottom="4px",
        ),
        # ── nav links ──
        rx.vstack(
            _nav_link("message-square", "Chat", "/", "chat"),
            _nav_link("wrench", "Tools", "/tools", "tools"),
            _nav_link("activity", "Monitor", "/monitor", "monitor"),
            _nav_link("settings", "Settings", "/settings", "settings"),
            spacing="1",
            width="100%",
            padding_x="8px",
            padding_top="4px",
        ),
        rx.separator(size="4", color=SB_BORDER),
        # ── new chat + search ──
        rx.vstack(
            rx.button(
                rx.icon("plus", size=14),
                "New Chat",
                variant="outline",
                width="100%",
                cursor="pointer",
                color="white",
                size="1",
                style={"border_color": "#334155", "&:hover": {"background": SB_HOVER, "border_color": "#475569"}},
                on_click=State.new_chat,
                disabled=State.is_loading,
            ),
            rx.hstack(
                rx.icon("search", size=13, color=SB_TEXT, flex_shrink="0"),
                rx.el.input(
                    on_change=State.set_session_search,
                    placeholder="Search…",
                    style={
                        "background": "transparent",
                        "border": "none",
                        "color": SB_TEXT_HI,
                        "font-size": "12px",
                        "outline": "none",
                        "width": "100%",
                        "padding": "0",
                        "::placeholder": {"color": "#475569"},
                    },
                ),
                background=SB_HOVER,
                border_radius="6px",
                padding="5px 8px",
                spacing="2",
                align="center",
                width="100%",
            ),
            spacing="2",
            padding_x="10px",
            width="100%",
        ),
        # ── session lists ──
        rx.box(
            rx.cond(
                State.has_filtered_pinned,
                rx.box(
                    _section_label("PINNED"),
                    rx.vstack(
                        rx.foreach(State.filtered_pinned, _session_item), width="100%", spacing="0", padding_x="4px"
                    ),
                ),
                rx.fragment(),
            ),
            _section_label("RECENT"),
            rx.vstack(rx.foreach(State.filtered_unpinned, _session_item), width="100%", spacing="0", padding_x="4px"),
            width="100%",
            overflow_y="auto",
            flex="1",
            min_height="0",
        ),
        # ── footer ──
        rx.hstack(
            rx.hstack(
                rx.icon("radio", size=10, color="#22c55e"),
                rx.text(
                    State.backend_url,
                    size="1",
                    color="#475569",
                    overflow="hidden",
                    text_overflow="ellipsis",
                    white_space="nowrap",
                ),
                spacing="2",
                align="center",
                flex="1",
                min_width="0",
            ),
            rx.tooltip(
                rx.icon_button(
                    rx.cond(State.dark_mode, rx.icon("sun", size=14), rx.icon("moon", size=14)),
                    variant="ghost",
                    size="1",
                    color=SB_TEXT,
                    cursor="pointer",
                    on_click=State.toggle_dark_mode,
                    _hover={"background": SB_HOVER, "color": "white"},
                ),
                content=rx.cond(State.dark_mode, "Light mode", "Dark mode"),
            ),
            padding="8px 14px",
            width="100%",
            align="center",
            border_top=f"1px solid {SB_BORDER}",
        ),
        height="100%",
        spacing="1",
    )


# ────────────────────────────────────────────
#  Shared layout
# ────────────────────────────────────────────


def base_layout(content: rx.Component, *scripts: str) -> rx.Component:
    return rx.box(
        rx.el.style(CUSTOM_CSS),
        rx.hstack(
            rx.cond(
                State.sidebar_visible,
                rx.box(
                    sidebar(),
                    width="280px",
                    min_width="280px",
                    height="100vh",
                    background=SB_BG,
                    border_right=f"1px solid {SB_BORDER}",
                ),
                rx.fragment(),
            ),
            content,
            spacing="0",
            width="100%",
            height="100vh",
        ),
        *[rx.script(s) for s in scripts],
        class_name=rx.cond(State.dark_mode, "dark", ""),
    )


# ────────────────────────────────────────────
#  Message components
# ────────────────────────────────────────────


def _md_map():
    return {
        "h1": lambda text: rx.heading(text, size="6", weight="bold", color="var(--heading)", margin_y="0.5em"),
        "h2": lambda text: rx.heading(text, size="5", weight="bold", color="var(--heading)", margin_y="0.4em"),
        "h3": lambda text: rx.heading(text, size="4", weight="medium", color="var(--heading)", margin_y="0.3em"),
        "p": lambda text: rx.text(text, size="3", color="var(--text-1)", line_height="1.7", margin_bottom="0.5em"),
        "code": lambda text: rx.code(text, color_scheme="iris", variant="ghost", size="2"),
        "pre": lambda text, **props: rx.box(
            rx.hstack(
                rx.text(
                    props.get("language", "code"),
                    size="1",
                    color="#94a3b8",
                    weight="medium",
                    text_transform="uppercase",
                    letter_spacing="0.05em",
                ),
                rx.spacer(),
                rx.tooltip(
                    rx.icon_button(
                        rx.icon("clipboard", size=12),
                        variant="ghost",
                        size="1",
                        cursor="pointer",
                        on_click=State.copy_text(text),
                        style={"color": "#94a3b8", "&:hover": {"color": "#e2e8f0"}},
                    ),
                    content="Copy code",
                ),
                padding="8px 14px",
                width="100%",
                align="center",
            ),
            rx.el.pre(
                rx.el.code(text),
                style={
                    "padding": "0 14px 14px",
                    "overflow-x": "auto",
                    "font-size": "13px",
                    "line-height": "1.6",
                    "margin": "0",
                    "color": "#e2e8f0",
                },
            ),
            border_radius="8px",
            overflow="hidden",
            margin_y="8px",
            background="var(--code-bg)",
        ),
    }


def _thought_collapsible(thought: str) -> rx.Component:
    return rx.box(
        rx.el.details(
            rx.el.summary(
                rx.hstack(
                    rx.icon("brain", size=12, color="var(--text-3)"),
                    rx.text("Thinking process", size="1", color="var(--text-3)"),
                    spacing="1",
                    align="center",
                    cursor="pointer",
                    _hover={"color": "var(--text-2)"},
                ),
            ),
            rx.box(
                rx.text(
                    thought,
                    size="1",
                    color="var(--text-3)",
                    white_space="pre-wrap",
                    line_height="1.5",
                ),
                padding="8px 12px",
                margin_top="4px",
                background="var(--bg-hover)",
                border_radius="6px",
                max_height="200px",
                overflow_y="auto",
            ),
        ),
        margin_bottom="6px",
    )


def _message_item(msg) -> rx.Component:
    is_user = msg.role == "user"
    return rx.box(
        rx.hstack(
            rx.avatar(
                fallback=rx.cond(is_user, "U", "M"),
                size="2",
                variant="solid",
                color_scheme=rx.cond(is_user, "gray", "iris"),
                radius="full",
                style={"flex_shrink": "0", "margin-top": "2px"},
            ),
            rx.box(
                rx.cond(
                    msg.thought != "",
                    _thought_collapsible(msg.thought),
                    rx.fragment(),
                ),
                rx.cond(
                    is_user,
                    rx.text(msg.content, white_space="pre-wrap", size="3", color="var(--text-1)", line_height="1.7"),
                    rx.markdown(msg.content, component_map=_md_map()),
                ),
                flex="1",
                min_width="0",
            ),
            width="100%",
            align_items="start",
            spacing="3",
        ),
        rx.box(
            rx.tooltip(
                rx.icon_button(
                    rx.icon("copy", size=13),
                    variant="ghost",
                    size="1",
                    cursor="pointer",
                    on_click=State.copy_text(msg.content),
                    color="var(--text-3)",
                    _hover={"color": "var(--text-1)"},
                ),
                content="Copy",
            ),
            class_name="msg-actions",
            position="absolute",
            top="6px",
            right="6px",
        ),
        position="relative",
        class_name="msg-row",
        width="100%",
        padding_y="14px",
        padding_x="24px",
    )


def _streaming_msg() -> rx.Component:
    return rx.hstack(
        rx.avatar(
            fallback="M",
            size="2",
            variant="solid",
            color_scheme="iris",
            radius="full",
            style={"flex_shrink": "0", "margin-top": "2px"},
        ),
        rx.box(
            rx.cond(
                State.has_thought,
                rx.box(
                    rx.hstack(
                        rx.spinner(size="1"),
                        rx.icon("brain", size=12, color="var(--text-3)"),
                        rx.text("Thinking…", size="1", color="var(--text-3)"),
                        spacing="1",
                        align="center",
                    ),
                    rx.box(
                        rx.text(
                            State.streaming_thought,
                            size="1",
                            color="var(--text-3)",
                            white_space="pre-wrap",
                            line_height="1.5",
                        ),
                        padding="8px 12px",
                        margin_top="4px",
                        background="var(--bg-hover)",
                        border_radius="6px",
                        max_height="120px",
                        overflow_y="auto",
                    ),
                    margin_bottom="6px",
                ),
                rx.fragment(),
            ),
            rx.cond(
                State.is_streaming,
                rx.fragment(
                    rx.markdown(State.streaming_content, component_map=_md_map()),
                    rx.el.span("▍", class_name="cursor-blink", style={"color": ACCENT, "font_size": "18px"}),
                ),
                rx.cond(
                    State.think_enabled,
                    rx.hstack(
                        rx.spinner(size="1"),
                        rx.icon("brain", size=14, color="var(--text-3)"),
                        rx.text("Thinking…", size="2", color="var(--text-3)"),
                        spacing="2",
                        align="center",
                    ),
                    rx.hstack(
                        rx.spinner(size="1"),
                        rx.icon("sparkles", size=14, color="var(--text-3)"),
                        rx.text("Generating…", size="2", color="var(--text-3)"),
                        spacing="2",
                        align="center",
                    ),
                ),
            ),
            flex="1",
            min_width="0",
        ),
        width="100%",
        align_items="start",
        spacing="3",
        padding_y="14px",
        padding_x="24px",
    )


def _tool_status_list() -> rx.Component:
    return rx.box(
        rx.foreach(
            State.tool_messages,
            lambda msg: rx.box(
                rx.text(msg, size="1", color="var(--tool-text)"),
                padding="4px 12px",
                background="var(--tool-bg)",
                border_radius="6px",
                margin_bottom="4px",
            ),
        ),
        padding_x="24px",
        padding_bottom="8px",
        padding_left="60px",
    )


# ── empty state ──


def _suggestion(emoji: str, title: str, prompt_text: str) -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.text(emoji, size="3", flex_shrink="0"),
            rx.text(title, size="2", color="var(--text-2)"),
            align="center",
            spacing="2",
            width="100%",
        ),
        padding="10px 14px",
        border="1px solid var(--border)",
        border_radius="10px",
        cursor="pointer",
        _hover={
            "background": "var(--bg-hover)",
            "border_color": "var(--border-hover)",
            "box_shadow": "var(--shadow-sm)",
        },
        transition="all 0.15s",
        on_click=State.use_suggestion(prompt_text),
    )


def _empty_state() -> rx.Component:
    return rx.center(
        rx.vstack(
            rx.box(
                rx.icon("sparkles", size=32, color=ACCENT, stroke_width=1.5),
                padding="16px",
                background="var(--accent-soft)",
                border_radius="16px",
            ),
            rx.heading("Hi, how can I help?", size="5", weight="medium", color="var(--heading)", text_align="center"),
            rx.hstack(
                _suggestion("💡", "Explain something", "Explain quantum computing in simple terms"),
                _suggestion("✍️", "Help me write", "Draft a professional email about project updates"),
                spacing="2",
                width="100%",
            ),
            rx.hstack(
                _suggestion("🔍", "Analyze a topic", "What are the pros and cons of microservices?"),
                _suggestion("🧩", "Debug my code", "How do I debug a memory leak in Python?"),
                spacing="2",
                width="100%",
            ),
            align="center",
            spacing="4",
            padding="24px",
            max_width="480px",
            width="100%",
        ),
        flex="1",
        width="100%",
    )


# ── dialogs ──


def _rename_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Rename Session", size="4", weight="bold", color="var(--text-1)"),
            rx.vstack(
                rx.el.input(
                    id="rename-input",
                    on_change=State.set_rename_input,
                    placeholder="Enter a title…",
                    style={
                        "width": "100%",
                        "padding": "8px 12px",
                        "border": "1px solid var(--border)",
                        "border-radius": "8px",
                        "font-size": "14px",
                        "background": "var(--bg-page)",
                        "color": "var(--text-1)",
                        "outline": "none",
                        "font-family": "inherit",
                    },
                ),
                rx.hstack(
                    rx.button(
                        "Cancel",
                        variant="soft",
                        color_scheme="gray",
                        cursor="pointer",
                        on_click=State.handle_rename_dialog(False),
                    ),
                    rx.button(
                        "Save",
                        color_scheme="iris",
                        cursor="pointer",
                        on_click=State.rename_session,
                        custom_attrs={"data-rename-save": "1"},
                    ),
                    spacing="3",
                    justify="end",
                    width="100%",
                ),
                spacing="4",
                width="100%",
            ),
            max_width="420px",
            style={"background": "var(--bg-card)"},
        ),
        open=State.rename_dialog_open,
        on_open_change=State.handle_rename_dialog,
    )


def _confirmation_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(
                rx.hstack(
                    rx.icon("shield-alert", size=20, color="#f59e0b"),
                    rx.text("Confirm tool call", size="4", weight="bold", color="var(--text-1)"),
                    spacing="2",
                    align="center",
                ),
            ),
            rx.vstack(
                rx.vstack(
                    rx.text("Tool", size="2", weight="medium", color="var(--text-2)"),
                    rx.box(
                        rx.text(State.confirm_tool_name, size="2", weight="medium", color="var(--text-1)"),
                        padding="8px 12px",
                        background="var(--bg-page)",
                        border="1px solid var(--border)",
                        border_radius="6px",
                        width="100%",
                    ),
                    spacing="1",
                    width="100%",
                ),
                rx.vstack(
                    rx.text("Arguments", size="2", weight="medium", color="var(--text-2)"),
                    rx.box(
                        rx.el.pre(
                            rx.el.code(State.confirm_arguments),
                            style={
                                "font-size": "12px",
                                "line-height": "1.5",
                                "margin": "0",
                                "color": "var(--text-1)",
                                "white-space": "pre-wrap",
                                "word-break": "break-all",
                            },
                        ),
                        padding="8px 12px",
                        background="var(--bg-page)",
                        border="1px solid var(--border)",
                        border_radius="6px",
                        width="100%",
                        max_height="200px",
                        overflow_y="auto",
                    ),
                    spacing="1",
                    width="100%",
                ),
                rx.hstack(
                    rx.button(
                        rx.icon("x", size=14),
                        "Deny",
                        variant="soft",
                        color_scheme="red",
                        size="2",
                        cursor="pointer",
                        on_click=State.confirm_tool_decision("deny"),
                    ),
                    rx.spacer(),
                    rx.button(
                        rx.icon("check", size=14),
                        "Allow",
                        variant="solid",
                        color_scheme="iris",
                        size="2",
                        cursor="pointer",
                        on_click=State.confirm_tool_decision("allow"),
                    ),
                    rx.button(
                        rx.icon("check-check", size=14),
                        "Always allow",
                        variant="outline",
                        color_scheme="green",
                        size="2",
                        cursor="pointer",
                        on_click=State.confirm_tool_decision("always_allow"),
                    ),
                    spacing="3",
                    width="100%",
                    align="center",
                ),
                spacing="4",
                width="100%",
            ),
            max_width="480px",
            style={"background": "var(--bg-card)"},
        ),
        open=State.confirm_dialog_open,
    )


# ── chat input ──


def _file_icon(f) -> rx.Component:
    return rx.cond(
        f.is_image,
        rx.icon("image", size=14, color="#8b5cf6", flex_shrink="0"),
        rx.icon("file-text", size=14, color="#6366f1", flex_shrink="0"),
    )


def _file_chip(f) -> rx.Component:
    return rx.box(
        rx.hstack(
            _file_icon(f),
            rx.vstack(
                rx.text(
                    f.name,
                    size="1",
                    weight="medium",
                    color="var(--text-1)",
                    overflow="hidden",
                    text_overflow="ellipsis",
                    white_space="nowrap",
                    max_width="140px",
                ),
                rx.text(
                    rx.cond(f.is_image, "Image", "Document"),
                    size="1",
                    color="var(--text-3)",
                ),
                spacing="0",
            ),
            rx.icon_button(
                rx.icon("x", size=12),
                variant="ghost",
                size="1",
                color="var(--text-3)",
                cursor="pointer",
                on_click=State.remove_pending_file(f.path),
                _hover={"color": "var(--text-1)", "background": "var(--bg-hover)"},
                style={"flex-shrink": "0"},
            ),
            spacing="2",
            align="center",
        ),
        padding="6px 10px",
        border="1px solid var(--border)",
        border_radius="10px",
        background="var(--bg-card)",
        _hover={"border_color": "var(--border-hover)", "box_shadow": "var(--shadow-sm)"},
        transition="all .12s",
    )


def _pending_files_bar() -> rx.Component:
    return rx.cond(
        State.has_pending_files,
        rx.box(
            rx.hstack(
                rx.foreach(State.pending_files, _file_chip),
                rx.tooltip(
                    rx.icon_button(
                        rx.icon("x", size=13),
                        variant="ghost",
                        size="1",
                        color="var(--text-3)",
                        cursor="pointer",
                        on_click=State.clear_pending_files,
                        _hover={"color": "var(--text-1)"},
                    ),
                    content="Clear all",
                ),
                spacing="2",
                align="center",
                flex_wrap="wrap",
            ),
            max_width="768px",
            margin_x="auto",
            width="100%",
            padding_x="24px",
            padding_top="8px",
        ),
        rx.fragment(),
    )


def _chat_input() -> rx.Component:
    return rx.box(
        _pending_files_bar(),
        rx.upload.root(
            rx.box(
                rx.box(
                    rx.hstack(
                        rx.text_area(
                            id="chat-input",
                            value=State.draft,
                            on_change=State.set_draft,
                            placeholder="Message Yumi…",
                            rows="1",
                            disabled=State.chat_textarea_disabled,
                            resize="none",
                            variant="surface",
                            size="2",
                            radius="medium",
                            style={
                                "width": "100%",
                                "min-height": "44px",
                                "max-height": "160px",
                                "padding": "10px 48px 10px 14px",
                                "overflow-y": "hidden",
                                "border": "1px solid var(--border)",
                                "border-radius": "12px",
                                "font-size": "14px",
                                "line-height": "1.5",
                                "background": "var(--bg-card)",
                                "color": "var(--text-1)",
                                "outline": "none",
                            },
                        ),
                        rx.cond(
                            State.is_loading,
                            rx.icon_button(
                                rx.spinner(size="2"),
                                id="send-btn",
                                size="2",
                                variant="solid",
                                color_scheme="iris",
                                radius="full",
                                disabled=True,
                                style={
                                    "position": "absolute",
                                    "right": "8px",
                                    "bottom": "8px",
                                    "flex-shrink": "0",
                                },
                            ),
                            rx.icon_button(
                                rx.icon("arrow-up", size=16),
                                id="send-btn",
                                size="2",
                                variant="solid",
                                color_scheme="iris",
                                radius="full",
                                cursor="pointer",
                                on_click=State.send_message,
                                style={
                                    "position": "absolute",
                                    "right": "8px",
                                    "bottom": "8px",
                                    "flex-shrink": "0",
                                },
                            ),
                        ),
                        width="100%",
                        position="relative",
                    ),
                    rx.hstack(
                        rx.tooltip(
                            rx.upload.root(
                                rx.box(
                                    rx.icon("paperclip", size=15, color="var(--text-3)"),
                                    padding="5px",
                                    border_radius="6px",
                                    display="flex",
                                    align_items="center",
                                    justify_content="center",
                                    cursor="pointer",
                                    _hover={"background": "var(--bg-hover)", "color": "var(--text-2)"},
                                    transition="all .12s",
                                ),
                                id="yumi_chat_upload",
                                max_size=_MAX_CHAT_UPLOAD_BYTES,
                                multiple=True,
                                no_drag=True,
                                padding="0",
                                border="none",
                                background="transparent",
                                min_height="0",
                                on_drop=State.handle_chat_file_upload,
                            ),
                            content="Upload files or audio (images, PDF, Word, text, etc.)",
                        ),
                        rx.tooltip(
                            rx.box(
                                rx.hstack(
                                    rx.icon("brain", size=13),
                                    rx.text("Think", size="1"),
                                    spacing="1",
                                    align="center",
                                ),
                                on_click=State.toggle_think,
                                cursor="pointer",
                                padding="4px 8px",
                                border_radius="6px",
                                background=rx.cond(State.think_enabled, "var(--iris-3)", "transparent"),
                                color=rx.cond(State.think_enabled, "var(--iris-11)", "var(--text-3)"),
                                border=rx.cond(State.think_enabled, "1px solid var(--iris-6)", "1px solid transparent"),
                                _hover={"background": rx.cond(State.think_enabled, "var(--iris-4)", "var(--bg-hover)")},
                                transition="all .12s",
                            ),
                            content=rx.cond(State.think_enabled, "Deep thinking on", "Enable deep thinking"),
                        ),
                        rx.spacer(),
                        spacing="2",
                        align="center",
                        padding_top="4px",
                    ),
                    max_width="768px",
                    margin_x="auto",
                    width="100%",
                    custom_attrs={"data-yumi-chat-input": ""},
                ),
                padding_x="24px",
                padding_y="12px",
                width="100%",
            ),
            id="yumi_chat_drop",
            max_size=_MAX_CHAT_UPLOAD_BYTES,
            multiple=True,
            no_click=True,
            border="none",
            background="transparent",
            width="100%",
            on_drop=State.handle_chat_file_upload,
            drag_active_style={
                "outline": "2px dashed var(--iris-9)",
                "outline_offset": "4px",
                "border_radius": "12px",
                "background": "var(--iris-2)",
            },
        ),
        border_top="1px solid var(--border)",
        background="var(--bg-page)",
        width="100%",
    )


# ── chat header ──


def _chat_header() -> rx.Component:
    return rx.hstack(
        rx.cond(
            State.sidebar_visible == False,  # noqa: E712
            rx.tooltip(
                rx.icon_button(
                    rx.icon("panel-left", size=18),
                    variant="ghost",
                    size="2",
                    cursor="pointer",
                    on_click=State.toggle_sidebar,
                    color="var(--text-2)",
                ),
                content="Show sidebar",
            ),
            rx.fragment(),
        ),
        rx.text(
            State.current_title,
            size="3",
            weight="medium",
            color="var(--heading)",
            overflow="hidden",
            text_overflow="ellipsis",
            white_space="nowrap",
            flex="1",
            min_width="0",
        ),
        rx.hstack(
            rx.tooltip(
                rx.icon_button(
                    rx.cond(State.is_current_pinned, rx.icon("pin-off", size=15), rx.icon("pin", size=15)),
                    variant="ghost",
                    size="1",
                    cursor="pointer",
                    on_click=State.toggle_pin_current,
                    color="var(--text-3)",
                    _hover={"color": "var(--text-1)"},
                ),
                content=rx.cond(State.is_current_pinned, "Unpin", "Pin"),
            ),
            rx.tooltip(
                rx.icon_button(
                    rx.icon("pencil", size=15),
                    variant="ghost",
                    size="1",
                    cursor="pointer",
                    on_click=State.handle_rename_dialog(True),
                    color="var(--text-3)",
                    _hover={"color": "var(--text-1)"},
                ),
                content="Rename",
            ),
            rx.tooltip(
                rx.icon_button(
                    rx.icon("trash-2", size=15),
                    variant="ghost",
                    size="1",
                    cursor="pointer",
                    on_click=State.delete_session(State.session_id),
                    disabled=State.is_loading,
                    color="var(--text-3)",
                    _hover={"color": "var(--text-1)"},
                ),
                content="Delete",
            ),
            spacing="0",
            align="center",
        ),
        width="100%",
        align="center",
        padding_x="24px",
        padding_y="10px",
        min_height="48px",
        border_bottom="1px solid var(--border)",
    )


# ── chat content ──


def _chat_content() -> rx.Component:
    return rx.vstack(
        _chat_header(),
        rx.box(
            rx.cond(
                State.show_empty,
                _empty_state(),
                rx.vstack(
                    rx.foreach(State.messages, _message_item),
                    rx.cond(State.has_tool_messages, _tool_status_list(), rx.fragment()),
                    rx.cond(State.is_loading, _streaming_msg(), rx.fragment()),
                    width="100%",
                    spacing="0",
                    max_width="768px",
                    margin_x="auto",
                ),
            ),
            rx.cond(
                State.error_message != "",
                rx.box(
                    rx.hstack(
                        rx.icon("circle-alert", size=13, color="#ef4444"),
                        rx.text(State.error_message, size="1", color="#ef4444"),
                        spacing="2",
                        align="center",
                    ),
                    padding="8px 12px",
                    background="var(--error-bg)",
                    border_radius="8px",
                    margin_x="auto",
                    margin_bottom="4px",
                    max_width="768px",
                ),
                rx.fragment(),
            ),
            rx.fragment(),
            id="msg-scroll",
            flex="1",
            overflow_y="auto",
            width="100%",
            padding_bottom="8px",
        ),
        _chat_input(),
        _rename_dialog(),
        _confirmation_dialog(),
        flex="1",
        height="100vh",
        spacing="0",
        background="var(--bg-page)",
        min_width="0",
    )


# ────────────────────────────────────────────
#  Settings page content
# ────────────────────────────────────────────


def _settings_section(title: str, icon_name: str, *children) -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.center(
                rx.icon(icon_name, size=18, color=ACCENT),
                width="34px",
                height="34px",
                border_radius="9px",
                background="var(--accent-soft)",
                flex_shrink="0",
            ),
            rx.text(title, size="3", weight="medium", color="var(--text-1)"),
            spacing="2",
            align="center",
            padding="14px 16px",
            border_bottom="1px solid var(--border)",
        ),
        rx.vstack(*children, spacing="3", padding="16px", width="100%"),
        border="1px solid var(--border)",
        border_radius="12px",
        background="var(--bg-card)",
        width="100%",
        _hover={"border_color": "var(--border-hover)"},
        transition="border-color 0.15s",
    )


def _model_row(label: str, value) -> rx.Component:
    return rx.hstack(
        rx.text(label, size="2", color="var(--text-2)", min_width="80px"),
        rx.text(value, size="2", weight="medium", color="var(--text-1)"),
        spacing="2",
        align="center",
        width="100%",
    )


def _model_section() -> rx.Component:
    return _settings_section(
        "Model",
        "brain",
        _model_row("Chat:", State.model_summary),
        _model_row("Embedding:", State.embed_summary),
        rx.hstack(
            rx.button(
                rx.icon("pencil", size=14),
                "Change Model",
                variant="outline",
                size="1",
                cursor="pointer",
                on_click=State.open_model_dialog,
            ),
            width="100%",
            justify="end",
        ),
    )


def _memory_context_section() -> rx.Component:
    return _settings_section(
        "Conversation context",
        "layers",
        rx.text(
            "Controls history sent to the model: this session uses the last N messages on the timeline; cross-session related uses vector search over other sessions (requires embedding model configured).",
            size="2",
            color="var(--text-2)",
            line_height="1.5",
        ),
        _model_row("Current:", State.memory_context_summary),
        rx.hstack(
            rx.vstack(
                rx.text("Messages in this session", size="2", weight="medium", color="var(--text-2)"),
                rx.text("1–500, user and assistant", size="1", color="var(--text-3)"),
                rx.el.input(
                    type="number",
                    min=1,
                    max=500,
                    value=State.edit_memory_max_recent,
                    on_change=State.set_edit_memory_max_recent,
                    style={
                        "width": "100%",
                        "max-width": "120px",
                        "padding": "6px 10px",
                        "border": "1px solid var(--border)",
                        "border-radius": "6px",
                        "font-size": "13px",
                        "background": "var(--bg-page)",
                        "color": "var(--text-1)",
                        "outline": "none",
                        "font-family": "inherit",
                    },
                ),
                spacing="1",
                align="start",
                width="100%",
            ),
            rx.vstack(
                rx.text("Cross-session related count", size="2", weight="medium", color="var(--text-2)"),
                rx.text("0 to disable; 3–20 suggested", size="1", color="var(--text-3)"),
                rx.el.input(
                    type="number",
                    min=0,
                    max=100,
                    value=State.edit_memory_max_related,
                    on_change=State.set_edit_memory_max_related,
                    style={
                        "width": "100%",
                        "max-width": "120px",
                        "padding": "6px 10px",
                        "border": "1px solid var(--border)",
                        "border-radius": "6px",
                        "font-size": "13px",
                        "background": "var(--bg-page)",
                        "color": "var(--text-1)",
                        "outline": "none",
                        "font-family": "inherit",
                    },
                ),
                spacing="1",
                align="start",
                width="100%",
            ),
            spacing="6",
            width="100%",
            align="start",
            flex_wrap="wrap",
        ),
        rx.hstack(
            rx.button(
                rx.cond(
                    State.memory_context_saving,
                    rx.spinner(size="2"),
                    rx.text("Save context settings"),
                ),
                color_scheme="iris",
                size="1",
                cursor="pointer",
                on_click=State.save_memory_context,
                disabled=State.memory_context_saving,
            ),
            width="100%",
            justify="end",
        ),
    )


def _model_dialog() -> rx.Component:
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title("Model Configuration", size="4", weight="bold", color="var(--text-1)"),
            rx.vstack(
                rx.vstack(
                    rx.text("Chat Provider", size="2", weight="medium", color="var(--text-2)"),
                    rx.select(
                        ["ollama", "openai", "gemini", "claude", "deepseek"],
                        value=State.model_edit_chat_provider,
                        on_change=State.set_model_edit_chat_provider,
                        width="100%",
                        size="2",
                    ),
                    spacing="1",
                    width="100%",
                ),
                rx.vstack(
                    rx.text("Chat Model", size="2", weight="medium", color="var(--text-2)"),
                    rx.el.input(
                        id="edit-chat-model",
                        on_change=State.set_model_edit_chat_model,
                        placeholder="e.g. gemini-2.5-flash, gpt-4o, claude-sonnet-4-20250514, deepseek-chat, qwen3:8b",
                        style={
                            "width": "100%",
                            "padding": "6px 10px",
                            "border": "1px solid var(--border)",
                            "border-radius": "6px",
                            "font-size": "13px",
                            "background": "var(--bg-page)",
                            "color": "var(--text-1)",
                            "outline": "none",
                            "font-family": "inherit",
                        },
                    ),
                    spacing="1",
                    width="100%",
                ),
                rx.separator(color="var(--border)", size="4"),
                rx.vstack(
                    rx.text("Embedding Provider", size="2", weight="medium", color="var(--text-2)"),
                    rx.select(
                        ["ollama", "openai", "gemini", "claude"],
                        value=State.model_edit_embed_provider,
                        on_change=State.set_model_edit_embed_provider,
                        width="100%",
                        size="2",
                    ),
                    spacing="1",
                    width="100%",
                ),
                rx.vstack(
                    rx.text("Embedding Model", size="2", weight="medium", color="var(--text-2)"),
                    rx.el.input(
                        id="edit-embed-model",
                        on_change=State.set_model_edit_embed_model,
                        placeholder="e.g. text-embedding-3-small, nomic-embed-text",
                        style={
                            "width": "100%",
                            "padding": "6px 10px",
                            "border": "1px solid var(--border)",
                            "border-radius": "6px",
                            "font-size": "13px",
                            "background": "var(--bg-page)",
                            "color": "var(--text-1)",
                            "outline": "none",
                            "font-family": "inherit",
                        },
                    ),
                    spacing="1",
                    width="100%",
                ),
                rx.separator(color="var(--border)", size="4"),
                rx.vstack(
                    rx.text("API keys", size="2", weight="medium", color="var(--text-2)"),
                    rx.text(
                        "Saved in ~/.yumi/config.json. Leave blank to keep an existing key.",
                        size="1",
                        color="var(--text-2)",
                    ),
                    rx.vstack(
                        rx.hstack(
                            rx.text("OpenAI", size="2", weight="medium", color="var(--text-2)"),
                            rx.cond(
                                State.model_openai_key_saved,
                                rx.badge("saved", variant="surface", color_scheme="gray", size="1"),
                                rx.fragment(),
                            ),
                            spacing="2",
                            align="center",
                        ),
                        rx.el.input(
                            type="password",
                            autocomplete="off",
                            placeholder="OPENAI_API_KEY",
                            on_change=State.set_model_edit_openai_api_key,
                            style={
                                "width": "100%",
                                "padding": "6px 10px",
                                "border": "1px solid var(--border)",
                                "border-radius": "6px",
                                "font-size": "13px",
                                "background": "var(--bg-page)",
                                "color": "var(--text-1)",
                                "outline": "none",
                                "font-family": "inherit",
                            },
                        ),
                        spacing="1",
                        width="100%",
                    ),
                    rx.vstack(
                        rx.hstack(
                            rx.text("Gemini", size="2", weight="medium", color="var(--text-2)"),
                            rx.cond(
                                State.model_gemini_key_saved,
                                rx.badge("saved", variant="surface", color_scheme="gray", size="1"),
                                rx.fragment(),
                            ),
                            spacing="2",
                            align="center",
                        ),
                        rx.el.input(
                            type="password",
                            autocomplete="off",
                            placeholder="GEMINI_API_KEY",
                            on_change=State.set_model_edit_gemini_api_key,
                            style={
                                "width": "100%",
                                "padding": "6px 10px",
                                "border": "1px solid var(--border)",
                                "border-radius": "6px",
                                "font-size": "13px",
                                "background": "var(--bg-page)",
                                "color": "var(--text-1)",
                                "outline": "none",
                                "font-family": "inherit",
                            },
                        ),
                        spacing="1",
                        width="100%",
                    ),
                    rx.vstack(
                        rx.hstack(
                            rx.text("Anthropic (Claude)", size="2", weight="medium", color="var(--text-2)"),
                            rx.cond(
                                State.model_claude_key_saved,
                                rx.badge("saved", variant="surface", color_scheme="gray", size="1"),
                                rx.fragment(),
                            ),
                            spacing="2",
                            align="center",
                        ),
                        rx.el.input(
                            type="password",
                            autocomplete="off",
                            placeholder="ANTHROPIC_API_KEY",
                            on_change=State.set_model_edit_claude_api_key,
                            style={
                                "width": "100%",
                                "padding": "6px 10px",
                                "border": "1px solid var(--border)",
                                "border-radius": "6px",
                                "font-size": "13px",
                                "background": "var(--bg-page)",
                                "color": "var(--text-1)",
                                "outline": "none",
                                "font-family": "inherit",
                            },
                        ),
                        spacing="1",
                        width="100%",
                    ),
                    rx.vstack(
                        rx.hstack(
                            rx.text("DeepSeek", size="2", weight="medium", color="var(--text-2)"),
                            rx.cond(
                                State.model_deepseek_key_saved,
                                rx.badge("saved", variant="surface", color_scheme="gray", size="1"),
                                rx.fragment(),
                            ),
                            spacing="2",
                            align="center",
                        ),
                        rx.el.input(
                            type="password",
                            autocomplete="off",
                            placeholder="DEEPSEEK_API_KEY",
                            on_change=State.set_model_edit_deepseek_api_key,
                            style={
                                "width": "100%",
                                "padding": "6px 10px",
                                "border": "1px solid var(--border)",
                                "border-radius": "6px",
                                "font-size": "13px",
                                "background": "var(--bg-page)",
                                "color": "var(--text-1)",
                                "outline": "none",
                                "font-family": "inherit",
                            },
                        ),
                        spacing="1",
                        width="100%",
                    ),
                    rx.vstack(
                        rx.text("DeepSeek base URL (optional)", size="2", weight="medium", color="var(--text-2)"),
                        rx.el.input(
                            value=State.model_edit_deepseek_base_url,
                            placeholder="Default: https://api.deepseek.com",
                            on_change=State.set_model_edit_deepseek_base_url,
                            style={
                                "width": "100%",
                                "padding": "6px 10px",
                                "border": "1px solid var(--border)",
                                "border-radius": "6px",
                                "font-size": "13px",
                                "background": "var(--bg-page)",
                                "color": "var(--text-1)",
                                "outline": "none",
                                "font-family": "inherit",
                            },
                        ),
                        spacing="1",
                        width="100%",
                    ),
                    rx.vstack(
                        rx.text("OpenAI base URL (optional)", size="2", weight="medium", color="var(--text-2)"),
                        rx.el.input(
                            value=State.model_edit_openai_base_url,
                            placeholder="Custom OpenAI-compatible API base URL",
                            on_change=State.set_model_edit_openai_base_url,
                            style={
                                "width": "100%",
                                "padding": "6px 10px",
                                "border": "1px solid var(--border)",
                                "border-radius": "6px",
                                "font-size": "13px",
                                "background": "var(--bg-page)",
                                "color": "var(--text-1)",
                                "outline": "none",
                                "font-family": "inherit",
                            },
                        ),
                        spacing="1",
                        width="100%",
                    ),
                    spacing="3",
                    width="100%",
                ),
                rx.hstack(
                    rx.button(
                        "Cancel",
                        variant="soft",
                        color_scheme="gray",
                        cursor="pointer",
                        on_click=State.close_model_dialog,
                    ),
                    rx.button(
                        rx.cond(State.model_saving, rx.spinner(size="2"), rx.text("Save")),
                        color_scheme="iris",
                        cursor="pointer",
                        on_click=State.save_model_config,
                        disabled=State.model_saving,
                    ),
                    spacing="3",
                    justify="end",
                    width="100%",
                ),
                spacing="4",
                width="100%",
            ),
            max_width="520px",
            style={"background": "var(--bg-card)"},
        ),
        open=State.model_dialog_open,
        on_open_change=State.handle_model_dialog,
    )


def _prompt_section() -> rx.Component:
    return _settings_section(
        "System Prompt",
        "file-text",
        rx.vstack(
            rx.hstack(
                rx.text("Default Prompt", size="2", weight="medium", color="var(--text-2)"),
                rx.cond(
                    State.default_prompt_is_default,
                    rx.badge("Default", variant="surface", color_scheme="gray", size="1"),
                    rx.badge("Custom", variant="surface", color_scheme="iris", size="1"),
                ),
                spacing="2",
                align="center",
            ),
            rx.text("Applied to all new sessions", size="1", color="var(--text-3)"),
            spacing="1",
            width="100%",
        ),
        rx.cond(
            State.prompt_editing,
            rx.vstack(
                rx.el.textarea(
                    id="edit-default-prompt",
                    on_change=State.set_prompt_draft,
                    rows=6,
                    style={
                        "width": "100%",
                        "resize": "vertical",
                        "min-height": "100px",
                        "padding": "10px 12px",
                        "border": "1px solid var(--border)",
                        "border-radius": "8px",
                        "font-size": "13px",
                        "line-height": "1.5",
                        "background": "var(--bg-page)",
                        "color": "var(--text-1)",
                        "outline": "none",
                        "font-family": "inherit",
                    },
                ),
                rx.hstack(
                    rx.button(
                        "Reset to Default",
                        variant="soft",
                        color_scheme="gray",
                        size="1",
                        cursor="pointer",
                        on_click=State.reset_default_prompt,
                    ),
                    rx.spacer(),
                    rx.button(
                        "Cancel",
                        variant="soft",
                        color_scheme="gray",
                        size="1",
                        cursor="pointer",
                        on_click=State.cancel_edit_prompt,
                    ),
                    rx.button(
                        "Save",
                        color_scheme="iris",
                        size="1",
                        cursor="pointer",
                        on_click=State.save_default_prompt,
                    ),
                    spacing="2",
                    width="100%",
                ),
                spacing="2",
                width="100%",
            ),
            rx.vstack(
                rx.box(
                    rx.text(
                        State.default_prompt,
                        size="1",
                        color="var(--text-2)",
                        white_space="pre-wrap",
                        line_height="1.5",
                    ),
                    padding="10px 12px",
                    border="1px solid var(--border)",
                    border_radius="8px",
                    background="var(--bg-page)",
                    width="100%",
                    max_height="150px",
                    overflow_y="auto",
                ),
                rx.hstack(
                    rx.spacer(),
                    rx.button(
                        rx.icon("pencil", size=12),
                        "Edit",
                        variant="outline",
                        size="1",
                        cursor="pointer",
                        on_click=State.start_edit_prompt,
                    ),
                    width="100%",
                ),
                spacing="2",
                width="100%",
            ),
        ),
        rx.separator(color="var(--border)", size="4"),
        rx.vstack(
            rx.hstack(
                rx.text("Session Prompt", size="2", weight="medium", color="var(--text-2)"),
                rx.cond(
                    State.session_prompt_custom,
                    rx.badge("Custom", variant="surface", color_scheme="iris", size="1"),
                    rx.badge("Using Default", variant="surface", color_scheme="gray", size="1"),
                ),
                spacing="2",
                align="center",
            ),
            rx.text(
                rx.cond(
                    State.session_id != "",
                    "Override the system prompt for the current session only",
                    "Select a session first",
                ),
                size="1",
                color="var(--text-3)",
            ),
            spacing="1",
            width="100%",
        ),
        rx.cond(
            State.session_id != "",
            rx.cond(
                State.session_prompt_editing,
                rx.vstack(
                    rx.el.textarea(
                        id="edit-session-prompt",
                        on_change=State.set_session_prompt_draft,
                        rows=6,
                        style={
                            "width": "100%",
                            "resize": "vertical",
                            "min-height": "100px",
                            "padding": "10px 12px",
                            "border": "1px solid var(--border)",
                            "border-radius": "8px",
                            "font-size": "13px",
                            "line-height": "1.5",
                            "background": "var(--bg-page)",
                            "color": "var(--text-1)",
                            "outline": "none",
                            "font-family": "inherit",
                        },
                    ),
                    rx.hstack(
                        rx.cond(
                            State.session_prompt_custom,
                            rx.button(
                                "Use Default",
                                variant="soft",
                                color_scheme="gray",
                                size="1",
                                cursor="pointer",
                                on_click=State.reset_session_prompt,
                            ),
                            rx.fragment(),
                        ),
                        rx.spacer(),
                        rx.button(
                            "Cancel",
                            variant="soft",
                            color_scheme="gray",
                            size="1",
                            cursor="pointer",
                            on_click=State.cancel_edit_session_prompt,
                        ),
                        rx.button(
                            "Save",
                            color_scheme="iris",
                            size="1",
                            cursor="pointer",
                            on_click=State.save_session_prompt,
                        ),
                        spacing="2",
                        width="100%",
                    ),
                    spacing="2",
                    width="100%",
                ),
                rx.vstack(
                    rx.box(
                        rx.text(
                            State.session_prompt_display,
                            size="1",
                            color="var(--text-2)",
                            white_space="pre-wrap",
                            line_height="1.5",
                        ),
                        padding="10px 12px",
                        border="1px solid var(--border)",
                        border_radius="8px",
                        background="var(--bg-page)",
                        width="100%",
                        max_height="150px",
                        overflow_y="auto",
                    ),
                    rx.hstack(
                        rx.cond(
                            State.session_prompt_custom,
                            rx.button(
                                "Use Default",
                                variant="soft",
                                color_scheme="gray",
                                size="1",
                                cursor="pointer",
                                on_click=State.reset_session_prompt,
                            ),
                            rx.fragment(),
                        ),
                        rx.spacer(),
                        rx.button(
                            rx.icon("pencil", size=12),
                            "Edit",
                            variant="outline",
                            size="1",
                            cursor="pointer",
                            on_click=State.start_edit_session_prompt,
                        ),
                        width="100%",
                    ),
                    spacing="2",
                    width="100%",
                ),
            ),
            rx.fragment(),
        ),
    )


def _appearance_section() -> rx.Component:
    return _settings_section(
        "Appearance",
        "palette",
        rx.hstack(
            rx.text("Theme", size="2", color="var(--text-2)"),
            rx.spacer(),
            rx.hstack(
                rx.button(
                    rx.icon("moon", size=14),
                    "Dark",
                    variant=rx.cond(State.dark_mode, "solid", "outline"),
                    color_scheme="iris",
                    size="1",
                    cursor="pointer",
                    on_click=State.set_dark,
                ),
                rx.button(
                    rx.icon("sun", size=14),
                    "Light",
                    variant=rx.cond(State.dark_mode, "outline", "solid"),
                    color_scheme="iris",
                    size="1",
                    cursor="pointer",
                    on_click=State.set_light,
                ),
                spacing="2",
            ),
            width="100%",
            align="center",
        ),
    )


def _memory_section() -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.center(
                rx.icon("database", size=18, color="var(--text-3)"),
                width="34px",
                height="34px",
                border_radius="9px",
                background="var(--bg-hover)",
                flex_shrink="0",
            ),
            rx.vstack(
                rx.text("Memory", size="3", weight="medium", color="var(--text-1)"),
                rx.text("Cross-session memory and context settings", size="2", color="var(--text-3)"),
                spacing="1",
                flex="1",
                min_width="0",
            ),
            rx.badge("Coming soon", variant="surface", color_scheme="gray"),
            width="100%",
            align="center",
            spacing="3",
        ),
        padding="16px",
        border="1px solid var(--border)",
        border_radius="12px",
        background="var(--bg-card)",
        width="100%",
    )


def _settings_content() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.cond(
                State.sidebar_visible == False,  # noqa: E712
                rx.tooltip(
                    rx.icon_button(
                        rx.icon("panel-left", size=18),
                        variant="ghost",
                        size="2",
                        cursor="pointer",
                        on_click=State.toggle_sidebar,
                        color="var(--text-2)",
                    ),
                    content="Show sidebar",
                ),
                rx.fragment(),
            ),
            rx.text("Settings", size="4", weight="medium", color="var(--text-1)", flex="1"),
            width="100%",
            align="center",
            spacing="2",
            padding_x="24px",
            padding_y="10px",
            min_height="48px",
            border_bottom="1px solid var(--border)",
        ),
        rx.box(
            rx.hstack(
                rx.vstack(
                    _model_section(),
                    _memory_context_section(),
                    _appearance_section(),
                    spacing="4",
                    flex="1",
                    min_width="0",
                ),
                rx.vstack(
                    _prompt_section(),
                    _memory_section(),
                    spacing="4",
                    flex="1",
                    min_width="0",
                ),
                spacing="6",
                width="100%",
                padding="32px",
                max_width="1200px",
                align_items="start",
                margin_x="auto",
            ),
            flex="1",
            overflow_y="auto",
            width="100%",
        ),
        _model_dialog(),
        spacing="0",
        width="100%",
        height="100vh",
        background="var(--bg-page)",
        min_width="0",
        flex="1",
    )


# ────────────────────────────────────────────
#  Tools page content
# ────────────────────────────────────────────


def _tool_toggle_card(tool) -> rx.Component:
    disabled = tool["disabled"]
    needs_confirm = tool["require_confirmation"]
    return rx.hstack(
        rx.center(
            rx.icon("wrench", size=16, color=rx.cond(disabled, "var(--text-3)", ACCENT)),
            width="36px",
            height="36px",
            border_radius="8px",
            background=rx.cond(disabled, "var(--bg-hover)", "var(--accent-soft)"),
            flex_shrink="0",
        ),
        rx.vstack(
            rx.hstack(
                rx.text(
                    tool["name"],
                    size="2",
                    weight="medium",
                    color=rx.cond(disabled, "var(--text-3)", "var(--text-1)"),
                ),
                rx.cond(
                    needs_confirm,
                    rx.badge("Confirm", variant="surface", color_scheme="amber", size="1"),
                    rx.fragment(),
                ),
                spacing="2",
                align="center",
            ),
            rx.text(
                tool["description"],
                size="1",
                color="var(--text-3)",
                line_height="1.4",
                style={
                    "display": "-webkit-box",
                    "-webkit-line-clamp": "2",
                    "-webkit-box-orient": "vertical",
                    "overflow": "hidden",
                },
            ),
            spacing="1",
            flex="1",
            min_width="0",
        ),
        rx.hstack(
            rx.icon_button(
                rx.icon("shield", size=14),
                variant="ghost",
                size="1",
                cursor="pointer",
                on_click=State.toggle_confirmation(tool["name"], needs_confirm),
                color=rx.cond(needs_confirm, "#f59e0b", "var(--text-3)"),
                _hover={"color": rx.cond(needs_confirm, "#d97706", "var(--text-2)")},
                title="Enable or disable human confirmation before this tool runs",
            ),
            rx.switch(
                checked=disabled == False,  # noqa: E712
                on_change=lambda _v: State.toggle_tool(tool["name"]),
                size="1",
                flex_shrink="0",
            ),
            spacing="2",
            align="center",
            flex_shrink="0",
        ),
        width="100%",
        align="center",
        spacing="3",
        padding="12px 14px",
        border="1px solid var(--border)",
        border_radius="10px",
        background="var(--bg-card)",
        opacity=rx.cond(disabled, "0.5", "1"),
        _hover={"border_color": "var(--border-hover)"},
        transition="all 0.15s",
    )


def _edge_tool_toggle_card(tool: EdgeToolEntry) -> rx.Component:
    return rx.hstack(
        rx.center(
            rx.icon("cpu", size=14, color=rx.cond(tool.disabled, "var(--text-3)", ACCENT)),
            width="30px",
            height="30px",
            border_radius="7px",
            background=rx.cond(tool.disabled, "var(--bg-hover)", "var(--accent-soft)"),
            flex_shrink="0",
        ),
        rx.vstack(
            rx.hstack(
                rx.text(
                    tool.name,
                    size="2",
                    weight="medium",
                    color=rx.cond(tool.disabled, "var(--text-3)", "var(--text-1)"),
                ),
                rx.cond(
                    tool.require_confirmation,
                    rx.badge("Confirm", variant="surface", color_scheme="amber", size="1"),
                    rx.fragment(),
                ),
                spacing="2",
                align="center",
            ),
            rx.text(
                tool.description,
                size="1",
                color="var(--text-3)",
                line_height="1.4",
                style={
                    "display": "-webkit-box",
                    "-webkit-line-clamp": "2",
                    "-webkit-box-orient": "vertical",
                    "overflow": "hidden",
                },
            ),
            spacing="1",
            flex="1",
            min_width="0",
        ),
        rx.hstack(
            rx.icon_button(
                rx.icon("shield", size=12),
                variant="ghost",
                size="1",
                cursor="pointer",
                on_click=State.toggle_confirmation(tool.full_name, tool.require_confirmation),
                color=rx.cond(tool.require_confirmation, "#f59e0b", "var(--text-3)"),
                _hover={"color": rx.cond(tool.require_confirmation, "#d97706", "var(--text-2)")},
                title="Enable or disable human confirmation before this tool runs (including sensitive tools declared by edge devices)",
            ),
            rx.switch(
                checked=tool.disabled == False,  # noqa: E712
                on_change=lambda _v: State.toggle_tool(tool.full_name),
                size="1",
                flex_shrink="0",
            ),
            spacing="2",
            align="center",
            flex_shrink="0",
        ),
        width="100%",
        align="center",
        spacing="3",
        padding="8px 12px",
        border_radius="8px",
        background="var(--bg-page)",
        opacity=rx.cond(tool.disabled, "0.5", "1"),
        transition="all 0.15s",
    )


def _edge_device_card(device: EdgeDeviceEntry) -> rx.Component:
    return rx.box(
        rx.hstack(
            rx.center(
                rx.icon("monitor-smartphone", size=18, color=rx.cond(device.online, "#22c55e", "var(--text-3)")),
                width="36px",
                height="36px",
                border_radius="8px",
                background=rx.cond(device.online, "rgba(34,197,94,0.1)", "var(--bg-hover)"),
                flex_shrink="0",
            ),
            rx.vstack(
                rx.hstack(
                    rx.text(device.edge_name, size="2", weight="medium", color="var(--text-1)"),
                    rx.cond(
                        device.online,
                        rx.badge("Online", variant="surface", color_scheme="green", size="1"),
                        rx.badge("Offline", variant="surface", color_scheme="gray", size="1"),
                    ),
                    spacing="2",
                    align="center",
                ),
                rx.text(
                    rx.cond(device.online, "Tools available", "Device is offline"),
                    size="1",
                    color="var(--text-3)",
                ),
                spacing="1",
                flex="1",
            ),
            width="100%",
            align="center",
            spacing="3",
            padding="12px 14px",
            padding_bottom="8px",
        ),
        rx.vstack(
            rx.foreach(device.tools, _edge_tool_toggle_card),
            spacing="1",
            width="100%",
            padding_x="14px",
            padding_bottom="12px",
        ),
        border="1px solid var(--border)",
        border_radius="10px",
        background="var(--bg-card)",
        width="100%",
        _hover={"border_color": "var(--border-hover)"},
        transition="border-color 0.15s",
    )


def _section_header(icon_name: str, title: str, desc: str) -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.icon(icon_name, size=16, color="var(--text-3)"),
            rx.text(title, size="2", weight="medium", color="var(--text-2)"),
            spacing="2",
            align="center",
        ),
        rx.text(desc, size="1", color="var(--text-3)"),
        spacing="1",
    )


def _tools_main() -> rx.Component:
    return rx.vstack(
        rx.callout(
            "Configure what the agent may call: enable or disable server and edge tools, and optional "
            "confirmation before sensitive tools. This page is for control—not execution history (see Monitor).",
            icon="wrench",
            color_scheme="blue",
            size="1",
            width="100%",
        ),
        rx.hstack(
            rx.icon("search", size=14, color="var(--text-3)", flex_shrink="0"),
            rx.el.input(
                placeholder="Filter tools (server + edge)…",
                on_change=State.set_tools_search,
                style={
                    "flex": "1",
                    "min_width": "0",
                    "padding": "8px 10px",
                    "border_radius": "8px",
                    "border": "1px solid var(--border)",
                    "background": "var(--bg-page)",
                    "color": "var(--text-1)",
                    "font_size": "13px",
                },
            ),
            width="100%",
            align="center",
            spacing="2",
            padding_bottom="8px",
        ),
        _section_header("server", "Server tools", "Built-in capabilities you can turn on or off for this core"),
        rx.cond(
            State.has_server_tools,
            rx.cond(
                State.has_filtered_server_tools,
                rx.vstack(rx.foreach(State.filtered_server_tools, _tool_toggle_card), spacing="2", width="100%"),
                rx.center(
                    rx.text("No tools match your filter", size="2", color="var(--text-3)"),
                    padding="24px",
                    border="1px dashed var(--border)",
                    border_radius="10px",
                    width="100%",
                ),
            ),
            rx.center(
                rx.text("No server tools loaded", size="2", color="var(--text-3)"),
                padding="24px",
                border="1px dashed var(--border)",
                border_radius="10px",
                width="100%",
            ),
        ),
        _section_header(
            "wifi", "Edge devices", "Remote nodes and the tools they expose—same toggles as above, per device"
        ),
        rx.cond(
            State.has_edge_devices,
            rx.cond(
                State.has_filtered_edge_devices,
                rx.vstack(rx.foreach(State.filtered_edge_devices, _edge_device_card), spacing="3", width="100%"),
                rx.center(
                    rx.text("No edge tools match your filter", size="2", color="var(--text-3)"),
                    padding="24px",
                    border="1px dashed var(--border)",
                    border_radius="10px",
                    width="100%",
                ),
            ),
            rx.center(
                rx.vstack(
                    rx.icon("monitor-x", size=20, color="var(--text-3)"),
                    rx.text("No edge devices connected", size="2", color="var(--text-3)"),
                    rx.text("Run yumi --edge on a device to connect", size="1", color="var(--text-3)"),
                    align="center",
                    spacing="1",
                ),
                padding="32px",
                border="1px dashed var(--border)",
                border_radius="10px",
                width="100%",
            ),
        ),
        spacing="5",
        max_width="800px",
        width="100%",
        padding="32px",
        margin_x="auto",
    )


def _monitor_edge_row(edge: MonitorEdgeEntry) -> rx.Component:
    return rx.hstack(
        rx.text(edge.edge_name, size="2", weight="medium", color="var(--text-1)", flex="1", min_width="0"),
        rx.cond(
            edge.online,
            rx.badge("Online", variant="surface", color_scheme="green", size="1"),
            rx.badge("Offline", variant="surface", color_scheme="gray", size="1"),
        ),
        rx.hstack(
            rx.text(edge.tool_count, size="2", color="var(--text-3)"),
            rx.text("tools", size="2", color="var(--text-3)"),
            spacing="1",
            align="center",
        ),
        width="100%",
        align="center",
        spacing="3",
        padding="10px 12px",
        border_radius="8px",
        background="var(--bg-page)",
        border="1px solid var(--border)",
    )


def _trace_row(trace: ToolTraceEntry) -> rx.Component:
    return rx.hstack(
        rx.text(
            trace.ts,
            size="1",
            color="var(--text-3)",
            width="150px",
            flex_shrink="0",
            style={"font_family": "JetBrains Mono, monospace"},
        ),
        rx.text(
            trace.display_name,
            size="2",
            weight="medium",
            color="var(--text-1)",
            width="180px",
            flex_shrink="0",
            style={"overflow": "hidden", "text_overflow": "ellipsis", "white_space": "nowrap"},
        ),
        rx.text(
            trace.args_summary,
            size="1",
            color="var(--text-2)",
            flex="1",
            min_width="0",
            style={"word_break": "break-word"},
        ),
        rx.hstack(
            rx.text(trace.duration_ms, size="1", color="var(--text-3)"),
            rx.text("ms", size="1", color="var(--text-3)"),
            spacing="1",
            align="center",
            width="72px",
            flex_shrink="0",
        ),
        rx.box(rx.badge(trace.status, variant="surface", size="1", color_scheme="gray"), width="90px", flex_shrink="0"),
        width="100%",
        align="start",
        spacing="3",
        padding_y="8px",
        padding_x="4px",
        border_bottom="1px solid var(--border)",
    )


def _monitor_main() -> rx.Component:
    return rx.vstack(
        rx.callout(
            "This page is observability only: reachability and recent tool executions. "
            "To enable/disable tools or confirmation flags, use Tools.",
            icon="activity",
            color_scheme="gray",
            size="1",
            width="100%",
        ),
        _section_header(
            "network",
            "Connection snapshot",
            "Local agent core and edge nodes (auto-refresh ~5s). Online/offline and tool counts are informational—not the same as toggles on Tools.",
        ),
        rx.vstack(
            rx.hstack(
                rx.icon("server", size=16, color="var(--text-3)"),
                rx.text("Yumi core (this server)", size="2", weight="medium", color="var(--text-1)"),
                rx.badge("local", variant="surface", size="1"),
                spacing="2",
                align="center",
            ),
            rx.text(
                "Configure which built-in tools are allowed on the Tools page.",
                size="2",
                color="var(--text-3)",
            ),
            spacing="2",
            padding="14px",
            border_radius="10px",
            border="1px solid var(--border)",
            background="var(--bg-card)",
            width="100%",
        ),
        rx.cond(
            State.has_monitor_edges,
            rx.vstack(rx.foreach(State.monitor_edges_data, _monitor_edge_row), spacing="2", width="100%"),
            rx.center(
                rx.text("No edge nodes registered yet", size="2", color="var(--text-3)"),
                padding="20px",
                border="1px dashed var(--border)",
                border_radius="10px",
                width="100%",
            ),
        ),
        _section_header(
            "history",
            "Recent tool runs",
            "Execution log (arguments shortened on screen; Export NDJSON is complete). Filter by session id when needed.",
        ),
        rx.hstack(
            rx.el.input(
                placeholder="Session id (optional)",
                on_change=State.set_trace_session_filter,
                style={
                    "flex": "1",
                    "min_width": "0",
                    "max_width": "360px",
                    "padding": "8px 10px",
                    "border_radius": "8px",
                    "border": "1px solid var(--border)",
                    "background": "var(--bg-page)",
                    "color": "var(--text-1)",
                    "font_size": "13px",
                },
            ),
            rx.button("Apply filter", size="1", variant="outline", on_click=State.apply_trace_session_filter),
            rx.spacer(),
            rx.button("Export NDJSON", size="1", variant="soft", on_click=State.export_monitor_traces),
            width="100%",
            align="center",
            spacing="2",
            flex_wrap="wrap",
        ),
        rx.box(
            rx.vstack(
                rx.hstack(
                    rx.text(
                        "Time (UTC)", size="1", weight="bold", color="var(--text-3)", width="150px", flex_shrink="0"
                    ),
                    rx.text("Tool", size="1", weight="bold", color="var(--text-3)", width="180px", flex_shrink="0"),
                    rx.text("Arguments", size="1", weight="bold", color="var(--text-3)", flex="1", min_width="0"),
                    rx.text("Duration", size="1", weight="bold", color="var(--text-3)", width="72px", flex_shrink="0"),
                    rx.text("Status", size="1", weight="bold", color="var(--text-3)", width="90px", flex_shrink="0"),
                    width="100%",
                    spacing="3",
                    padding_x="4px",
                    padding_bottom="8px",
                    border_bottom="1px solid var(--border)",
                ),
                rx.cond(
                    State.has_monitor_traces,
                    rx.vstack(rx.foreach(State.monitor_traces, _trace_row), width="100%", spacing="0"),
                    rx.center(
                        rx.text("No traces yet — run a chat that invokes tools.", size="2", color="var(--text-3)"),
                        padding="28px",
                        width="100%",
                    ),
                ),
                spacing="0",
                width="100%",
                align="stretch",
            ),
            width="100%",
            overflow_x="auto",
        ),
        spacing="5",
        max_width="960px",
        width="100%",
        padding="32px",
        margin_x="auto",
    )


def _monitor_content() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.cond(
                State.sidebar_visible == False,  # noqa: E712
                rx.tooltip(
                    rx.icon_button(
                        rx.icon("panel-left", size=18),
                        variant="ghost",
                        size="2",
                        cursor="pointer",
                        on_click=State.toggle_sidebar,
                        color="var(--text-2)",
                    ),
                    content="Show sidebar",
                ),
                rx.fragment(),
            ),
            rx.text("Monitor", size="4", weight="medium", color="var(--text-1)", flex="1"),
            rx.tooltip(
                rx.icon_button(
                    rx.icon("refresh-cw", size=14),
                    variant="ghost",
                    size="1",
                    cursor="pointer",
                    on_click=State.refresh_monitor,
                    color="var(--text-3)",
                    _hover={"color": "var(--text-1)"},
                ),
                content="Refresh now",
            ),
            width="100%",
            align="center",
            spacing="2",
            padding_x="24px",
            padding_y="10px",
            min_height="48px",
            border_bottom="1px solid var(--border)",
        ),
        rx.box(
            _monitor_main(),
            flex="1",
            overflow_y="auto",
            width="100%",
        ),
        spacing="0",
        width="100%",
        height="100vh",
        background="var(--bg-page)",
        min_width="0",
        flex="1",
    )


def _tools_content() -> rx.Component:
    return rx.vstack(
        rx.hstack(
            rx.cond(
                State.sidebar_visible == False,  # noqa: E712
                rx.tooltip(
                    rx.icon_button(
                        rx.icon("panel-left", size=18),
                        variant="ghost",
                        size="2",
                        cursor="pointer",
                        on_click=State.toggle_sidebar,
                        color="var(--text-2)",
                    ),
                    content="Show sidebar",
                ),
                rx.fragment(),
            ),
            rx.text("Tools", size="4", weight="medium", color="var(--text-1)", flex="1"),
            rx.tooltip(
                rx.icon_button(
                    rx.icon("refresh-cw", size=14),
                    variant="ghost",
                    size="1",
                    cursor="pointer",
                    on_click=State.init_tools,
                    color="var(--text-3)",
                    _hover={"color": "var(--text-1)"},
                ),
                content="Refresh",
            ),
            width="100%",
            align="center",
            spacing="2",
            padding_x="24px",
            padding_y="10px",
            min_height="48px",
            border_bottom="1px solid var(--border)",
        ),
        rx.box(
            _tools_main(),
            flex="1",
            overflow_y="auto",
            width="100%",
        ),
        spacing="0",
        width="100%",
        height="100vh",
        background="var(--bg-page)",
        min_width="0",
        flex="1",
    )


# ────────────────────────────────────────────
#  Pages
# ────────────────────────────────────────────


def chat_page() -> rx.Component:
    return base_layout(_chat_content(), SCROLL_SCRIPT, TEXTAREA_SCRIPT)


def tools_page() -> rx.Component:
    return base_layout(_tools_content())


def monitor_page() -> rx.Component:
    return base_layout(_monitor_content())


def settings_page() -> rx.Component:
    return base_layout(_settings_content())


# ── app ──

app = rx.App(
    style={"::selection": {"background": "rgba(99, 102, 241, 0.2)"}},
    stylesheets=[
        "https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap",
        "https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&display=swap",
    ],
)
app.add_page(chat_page, route="/", on_load=State.initialize, title="Yumi")
app.add_page(tools_page, route="/tools", on_load=State.init_tools, title="Yumi · Tools")
app.add_page(monitor_page, route="/monitor", on_load=State.init_monitor, title="Yumi · Monitor")
app.add_page(settings_page, route="/settings", on_load=State.init_settings, title="Yumi · Settings")
