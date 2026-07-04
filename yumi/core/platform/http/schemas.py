"""Pydantic request/response models for the Yumi HTTP API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    prompt: str
    session_id: str = "default"
    think: bool = False


class FileUploadRequest(BaseModel):
    """JSON body for ``POST /uploads`` (base64 file)."""

    session_id: str = "default"
    filename: str
    content_base64: str


class TranscribeRequest(BaseModel):
    """JSON body for ``POST /stt/transcribe`` (base64 audio)."""

    session_id: str = "default"
    filename: str
    content_base64: str
    language: str | None = None


class TtsRequest(BaseModel):
    """JSON body for ``POST /tts/synthesize`` (returns audio bytes)."""

    text: str
    session_id: str = "default"
    voice: str | None = None
    language: str | None = None


class SystemPromptUpdateRequest(BaseModel):
    system_prompt: str


class MemoryCreateRequest(BaseModel):
    session_id: str
    role: str
    content: str
    thought: str | None = None


class MemoryUpdateRequest(BaseModel):
    content: str
    role: str | None = None


class SessionCreateRequest(BaseModel):
    title: str | None = None


class SessionUpdateRequest(BaseModel):
    title: str | None = None
    is_pinned: bool | None = None
    status: str | None = None


class ToolToggleRequest(BaseModel):
    tool_name: str
    disabled: bool


class ToolConfirmationToggleRequest(BaseModel):
    tool_name: str
    require_confirmation: bool


class ToolConfirmationResponse(BaseModel):
    call_id: str
    decision: str  # "allow" | "deny" | "always_allow"


class ModelConfigUpdateRequest(BaseModel):
    chat_provider: str | None = None
    chat_model: str | None = None
    embedding_provider: str | None = None
    embedding_model: str | None = None
    memory_max_recent_messages: int | None = Field(default=None, ge=1, le=500)
    memory_max_related_messages: int | None = Field(default=None, ge=0, le=100)
    chat_append_current_time: bool | None = None
    chat_append_tool_use_instruction: bool | None = None
    edge_tools_enable_dynamic_routing: bool | None = None
    edge_tools_retrieval_limit: int | None = Field(default=None, ge=0, le=200)
    stt_provider: str | None = None
    stt_backend: str | None = None
    stt_model: str | None = None
    stt_model_dir: str | None = None
    stt_language: str | None = None
    tts_provider: str | None = None
    tts_voice: str | None = None
    tts_model: str | None = None
    tts_api_key: str | None = None
    tts_language: str | None = None
    # Stored in ~/.yumi/config.json; omit or leave empty to keep existing value.
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    claude_api_key: str | None = None
    openai_base_url: str | None = None
    deepseek_api_key: str | None = None
    deepseek_base_url: str | None = None
    grok_api_key: str | None = None
    grok_base_url: str | None = None
    # web_search provider settings; keys are write-only like the LLM keys above.
    search_provider: str | None = None
    tavily_api_key: str | None = None
    brave_search_api_key: str | None = None
    serper_api_key: str | None = None
    searxng_base_url: str | None = None


class ChatDebugRequest(BaseModel):
    """Enable or disable NDJSON chat tracing for a session (writes under ~/.yumi/debug/chat_trace/)."""

    session_id: str = "default"
    enabled: bool


class SessionPromptRequest(BaseModel):
    system_prompt: str


class UIPreferencesRequest(BaseModel):
    dark_mode: bool = True
