"""Pydantic model for ~/.yumi/config.json."""

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class ModelConfig(BaseModel):
    chat_provider: str = "ollama"
    chat_model: str | None = None
    embedding_provider: str = "ollama"
    embedding_model: str | None = None
    embedding_dim: int | None = None
    system_prompt: str | None = None
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    gemini_api_key: str | None = None
    claude_api_key: str | None = None
    deepseek_api_key: str | None = None
    deepseek_base_url: str | None = None
    grok_api_key: str | None = None
    grok_base_url: str | None = None
    connection_code: str | None = None
    # web_search tool provider: auto | tavily | brave | serper | searxng | duckduckgo.
    # "auto" tries the first configured of tavily > brave > serper > searxng; the
    # keyless DuckDuckGo HTML endpoint is always the final fallback either way.
    search_provider: str = "auto"
    tavily_api_key: str | None = None
    brave_search_api_key: str | None = None
    serper_api_key: str | None = None
    searxng_base_url: str | None = None
    session_prompts: dict[str, str] = {}
    ui_dark_mode: bool = True
    lan_secret: str | None = None
    # Server-local tools only (names in TOOL_REGISTRY, not edge_*__*).
    local_tools_always_allow: list[str] = Field(default_factory=list)
    local_tools_force_confirm: list[str] = Field(default_factory=list)
    # Chat context: hard ceiling on transcript messages fetched per turn. With
    # compaction enabled this is a safety cap, not the primary control — the
    # token budget below decides when old turns get folded into the summary.
    memory_max_recent_messages: int = Field(default=120, ge=1, le=500)
    # Cross-session RAG snippets injected as a system block (0 = off).
    memory_max_related_messages: int = Field(default=15, ge=0, le=100)
    # Transcript compaction: the context grows append-only (provider prompt
    # caches hit every turn) until the transcript exceeds this token budget;
    # then the oldest turns are summarized into the session-summary block and
    # the watermark advances — ONE cache miss per compaction instead of a
    # sliding window missing on every turn.
    memory_compaction_enabled: bool = True
    memory_transcript_token_budget: int = Field(default=8000, ge=1000, le=64000)
    # How many of the newest messages stay verbatim after a compaction.
    memory_compaction_keep_tail_messages: int = Field(default=16, ge=4, le=100)
    # Appended to the system message each chat request (can disable to save tokens / avoid English policy text).
    chat_append_current_time: bool = True
    chat_append_tool_use_instruction: bool = True
    # IANA timezone (e.g. Pacific/Auckland) for user-facing wall clock: chat [Current Time],
    # proactive message context, proactive quiet hours, proactive daily send limit calendar.
    # Unset or null: those features use UTC for date windows; chat time fallback uses the host OS zone (see docs).
    # Legacy config key ``proactive_quiet_hours_timezone`` is still accepted on load.
    local_timezone: str | None = None
    # Tool routing: core server tools stay loaded; edge tools are scoped.
    # Modes: "sticky" (default) — edges the session actually uses (or names)
    # stay attached for the whole session, so the tools array only changes on
    # activation and the provider prompt cache survives between turns;
    # "per_turn" — legacy behavior: rank ALL edge tools against each request
    # and expose the top edge_tools_retrieval_limit (cache-hostile: the tools
    # array can change every turn); "off" — always expose everything.
    edge_tools_enable_dynamic_routing: bool = True
    edge_tools_routing_mode: str = Field(default="sticky", description="sticky | per_turn | off")
    edge_tools_retrieval_limit: int = Field(default=20, ge=0, le=200)
    # Sticky mode: soft cap on attached edge-tool schemas per session; the
    # least-recently-used edge is dropped when a new activation would exceed it.
    edge_tools_session_max: int = Field(default=96, ge=8, le=500)
    # A small edge is always fully exposed to the model regardless of the retrieval
    # limit / dynamic routing, so a freshly scaffolded edge with a handful of tools is
    # reliably callable without the user picking an exposure mode — and stays callable
    # even if an operator sets edge_tools_retrieval_limit to 0. Only edges with MORE
    # than this many tools fall back to ranked retrieval.
    edge_tools_always_expose_below: int = Field(default=10, ge=0, le=200)
    core_tools_always_include: bool = True
    core_tools_allow_disable: bool = True
    # Telegram bot (optional): token in config or TELEGRAM_BOT_TOKEN; empty allowed_user_ids = no restriction
    telegram_bot_token: str | None = None
    telegram_allowed_user_ids: list[int] = Field(default_factory=list)
    # Discord bot (optional): token in config or DISCORD_BOT_TOKEN; empty allowed_user_ids = no restriction
    discord_bot_token: str | None = None
    discord_allowed_user_ids: list[int] = Field(default_factory=list)
    # LINE Messaging API (optional): secrets in config or LINE_* env; empty line_allowed_user_ids = no restriction
    line_channel_secret: str | None = None
    line_channel_access_token: str | None = None
    line_bot_port: int = Field(default=8788, ge=1, le=65535)
    line_allowed_user_ids: list[str] = Field(default_factory=list)
    # Proactive messaging (optional): off / smart (probabilistic) / scheduled (fixed times or interval).
    # Legacy ``proactive_enabled`` is kept for JSON compatibility and is synced from ``proactive_mode`` after load.
    proactive_mode: str = Field(default="off", description="off | smart | scheduled")
    proactive_enabled: bool = False
    proactive_channels: list[str] = Field(default_factory=lambda: ["telegram"])
    proactive_session_ids: list[str] = Field(default_factory=list)
    proactive_daily_limit: int = Field(default=4, ge=0, le=100)
    proactive_quiet_hours: str = "00:30-08:30"
    proactive_check_interval_seconds: int = Field(default=900, ge=60, le=86400)
    proactive_min_idle_minutes: int = Field(default=45, ge=1, le=10080)
    proactive_unreplied_escalation_minutes: int = Field(default=180, ge=1, le=10080)
    proactive_profile: str = "default"
    proactive_profile_prompt: str | None = None
    proactive_tone_intensity: str = "gentle"
    proactive_smart_naturalness: str = Field(default="balanced", description="off | subtle | balanced")
    proactive_smart_max_unreplied_followups: int = Field(default=4, ge=1, le=20)
    # Jitter check loop sleep: sample in [base*(1-ratio), base*(1+ratio)] clamped to [60, 86400].
    proactive_check_interval_jitter_ratio: float = Field(default=0.15, ge=0.0, le=0.5)
    # Stable random scale for unreplied follow-up threshold (0 = exact escalation minutes).
    proactive_unreplied_escalation_jitter_ratio: float = Field(default=0.0, ge=0.0, le=0.5)
    # Probability each eligible check emits a proactive check-in (when not in unreplied escalation path).
    proactive_check_in_probability: float = Field(default=0.35, ge=0.0, le=1.0)
    # Scheduled mode: local wall-clock times (HH:MM in ``local_timezone``) and/or fixed interval.
    proactive_schedule_times: list[str] = Field(default_factory=list)
    proactive_schedule_interval_minutes: int | None = Field(
        default=None,
        description="Minutes between scheduled sends when set (5–10080). Null disables interval scheduling.",
    )
    proactive_schedule_require_idle: bool = True
    # Speech-to-text (optional at runtime): disabled by default; dependencies
    # ship in the base package, while Whisper weights download on demand.
    stt_provider: str = "disabled"
    stt_backend: str = "faster-whisper"
    stt_model: str | None = None
    stt_model_dir: str | None = None
    stt_language: str = "auto"
    # Voice session (mic capture + wake word). Only consulted when `yumi --server --voice` is passed;
    # the modifier sets YUMI_VOICE_ENABLED=1 which the API lifespan watches.
    voice_wake_word: str = "hi yumi"
    voice_porcupine_access_key: str | None = None
    voice_porcupine_keyword_path: str | None = None
    voice_porcupine_sensitivity: float = Field(default=0.5, ge=0.0, le=1.0)
    voice_input_device: int | None = None
    voice_vad_aggressiveness: int = Field(default=2, ge=0, le=3)
    voice_silence_ms: int = Field(default=800, ge=100, le=10000)
    voice_max_utterance_ms: int = Field(default=15000, ge=1000, le=60000)
    voice_owner_id: str | None = None
    # Text-to-speech (optional at runtime): spoken replies. "disabled" by
    # default. Provider is one of:
    #   system    - OS speech command (macOS `say` / Linux `espeak`), zero deps
    #   openai    - OpenAI audio/speech endpoint
    #   gemini    - Gemini native audio TTS
    #   grok      - xAI/Grok voice TTS endpoint
    #   dashscope - Qwen3-TTS via the Alibaba Cloud DashScope API (needs a key)
    #   qwen      - Qwen3-TTS run locally (heavy `tts-local` extra; realistically a GPU)
    tts_provider: str = "disabled"
    tts_voice: str | None = None
    tts_model: str | None = None
    tts_api_key: str | None = None
    tts_language: str = "auto"
    # Free-text delivery instruction for providers with natural-language style
    # control (gemini: prepended to the synthesis prompt; openai gpt-4o-*-tts:
    # sent as `instructions`). E.g. "speak as a cheerful young girl, light and
    # sweet, at a brisk natural pace". Ignored by providers without support.
    tts_style: str | None = None

    @field_validator("search_provider")
    @classmethod
    def _normalize_search_provider(cls, v: Any) -> str:
        s = (v or "auto").strip().lower()
        if s not in ("auto", "tavily", "brave", "serper", "searxng", "duckduckgo"):
            return "auto"
        return s

    @field_validator("proactive_mode")
    @classmethod
    def _normalize_proactive_mode(cls, v: Any) -> str:
        s = (v or "off").strip().lower()
        if s not in ("off", "smart", "scheduled"):
            return "off"
        return s

    @field_validator("proactive_schedule_times", mode="before")
    @classmethod
    def _proactive_schedule_times_before(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        if isinstance(v, list):
            return [str(item) for item in v]
        return []

    @field_validator("proactive_schedule_times")
    @classmethod
    def _validate_proactive_schedule_times(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for raw in v or []:
            s = str(raw).strip()
            if not s:
                continue
            parts = s.split(":", maxsplit=1)
            if len(parts) != 2:
                raise ValueError(f"Invalid proactive_schedule_times entry {raw!r}; use HH:MM")
            try:
                h = int(parts[0].strip())
                m = int(parts[1].strip())
            except ValueError as exc:
                raise ValueError(f"Invalid proactive_schedule_times entry {raw!r}") from exc
            if not (0 <= h <= 23 and 0 <= m <= 59):
                raise ValueError(f"Invalid proactive_schedule_times entry {raw!r}; hour 0–23, minute 0–59")
            out.append(f"{h:02d}:{m:02d}")
        return out

    @field_validator("proactive_schedule_interval_minutes")
    @classmethod
    def _validate_schedule_interval(cls, v: Any) -> int | None:
        if v is None:
            return None
        try:
            iv = int(v)
        except (TypeError, ValueError) as exc:
            raise ValueError("proactive_schedule_interval_minutes must be an integer or null") from exc
        if iv < 5 or iv > 10_080:
            raise ValueError("proactive_schedule_interval_minutes must be between 5 and 10080 (or null)")
        return iv

    @field_validator("proactive_smart_naturalness")
    @classmethod
    def _normalize_smart_naturalness(cls, v: Any) -> str:
        s = (v or "balanced").strip().lower()
        if s not in ("off", "subtle", "balanced"):
            return "balanced"
        return s

    @model_validator(mode="before")
    @classmethod
    def _config_before(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        d = dict(data)
        lt = d.get("local_timezone")
        legacy = d.get("proactive_quiet_hours_timezone")
        legacy_empty = legacy is None or (isinstance(legacy, str) and not legacy.strip())
        lt_empty = lt is None or (isinstance(lt, str) and not str(lt).strip())
        if lt_empty and not legacy_empty and isinstance(legacy, str):
            d["local_timezone"] = legacy.strip()
        pm = d.get("proactive_mode")
        pm_missing = pm is None or (isinstance(pm, str) and not str(pm).strip())
        if pm_missing:
            d["proactive_mode"] = "smart" if d.get("proactive_enabled") else "off"
        return d

    @model_validator(mode="after")
    def _sync_legacy_proactive_enabled(self) -> "ModelConfig":
        object.__setattr__(self, "proactive_enabled", self.proactive_mode != "off")
        return self


RECOMMENDED_CHAT_MODEL = "qwen3.5:9b"
RECOMMENDED_EMBEDDING_MODEL = "qwen3-embedding:0.6b"
RECOMMENDED_FASTEMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
RECOMMENDED_STT_MODEL = "base"

DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_GROK_BASE_URL = "https://api.x.ai/v1"

# Non-interactive chat model fallbacks. Interactive setup asks users to paste a
# model id from their provider's model list instead of presenting recommendations.
# First entry is used when env/CI setup has a provider key but no explicit model.
RECOMMENDED_CHAT_MODELS: dict[str, list[str]] = {
    "openai": ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini"],
    "claude": ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
    "gemini": ["gemini-3.1-pro-preview", "gemini-3.5-flash", "gemini-3-flash-preview"],
    "deepseek": ["deepseek-v4-flash", "deepseek-v4-pro"],
    "grok": ["grok-4.3", "grok-build-0.1"],
    "ollama": [RECOMMENDED_CHAT_MODEL],
}

# Providers that expose a text-embedding endpoint. Claude, DeepSeek, and Grok do not,
# so memory/tool-routing embeddings must use one of these (or be disabled).
EMBEDDING_CAPABLE_PROVIDERS: tuple[str, ...] = ("ollama", "openai", "gemini", "fastembed")

RECOMMENDED_EMBEDDING_MODELS: dict[str, str] = {
    "openai": "text-embedding-3-small",
    "gemini": "text-embedding-004",
    "ollama": RECOMMENDED_EMBEDDING_MODEL,
    "fastembed": RECOMMENDED_FASTEMBED_MODEL,
}


def embeddings_enabled(config: "ModelConfig") -> bool:
    """True when long-term-memory / tool-routing embeddings are configured.

    Embeddings are *off* when no model is set or the provider is the sentinel
    ``"disabled"``. The whole embedding pipeline already degrades to zero-vectors
    in that case (see ``EmbeddingProcessor``); this helper lets callers skip
    provider instantiation and availability checks entirely.
    """
    return bool(config.embedding_model) and (config.embedding_provider or "") not in ("", "disabled")
