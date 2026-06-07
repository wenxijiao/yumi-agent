"""Load/save ModelConfig JSON with environment-variable overrides."""

import json
import os

from pydantic import ValidationError
from yumi.core.features.config.model import ModelConfig
from yumi.core.features.config.paths import CONFIG_PATH, ensure_config_dir


def load_saved_model_config() -> ModelConfig:
    if not CONFIG_PATH.exists():
        return ModelConfig()

    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ModelConfig()

    try:
        return ModelConfig.model_validate(data)
    except Exception:
        return ModelConfig()


def load_model_config() -> ModelConfig:
    config = load_saved_model_config()

    chat_provider = os.getenv("YUMI_CHAT_PROVIDER")
    chat_model = os.getenv("YUMI_CHAT_MODEL")
    embedding_provider = os.getenv("YUMI_EMBEDDING_PROVIDER")
    embedding_model = os.getenv("YUMI_EMBED_MODEL")

    if chat_provider:
        config.chat_provider = chat_provider.strip()
    if chat_model:
        config.chat_model = chat_model.strip()
    if embedding_provider:
        config.embedding_provider = embedding_provider.strip()
    if embedding_model:
        config.embedding_model = embedding_model.strip()

    mem_recent = os.getenv("YUMI_MEMORY_MAX_RECENT")
    if mem_recent:
        try:
            config.memory_max_recent_messages = max(
                1,
                min(500, int(mem_recent.strip())),
            )
        except ValueError:
            pass
    mem_related = os.getenv("YUMI_MEMORY_MAX_RELATED")
    if mem_related:
        try:
            config.memory_max_related_messages = max(
                0,
                min(100, int(mem_related.strip())),
            )
        except ValueError:
            pass

    def _env_bool(name: str, current: bool) -> bool:
        raw = os.getenv(name)
        if raw is None or not str(raw).strip():
            return current
        v = str(raw).strip().lower()
        if v in ("0", "false", "no", "off"):
            return False
        if v in ("1", "true", "yes", "on"):
            return True
        return current

    config.chat_append_current_time = _env_bool("YUMI_CHAT_APPEND_CURRENT_TIME", config.chat_append_current_time)
    config.chat_append_tool_use_instruction = _env_bool(
        "YUMI_CHAT_APPEND_TOOL_INSTRUCTION", config.chat_append_tool_use_instruction
    )
    config.edge_tools_enable_dynamic_routing = _env_bool(
        "YUMI_EDGE_TOOLS_DYNAMIC_ROUTING", config.edge_tools_enable_dynamic_routing
    )
    mode_from_env = False
    pm_env = os.getenv("YUMI_PROACTIVE_MODE")
    if pm_env and str(pm_env).strip():
        s = pm_env.strip().lower()
        if s in ("off", "smart", "scheduled"):
            config.proactive_mode = s
            mode_from_env = True

    enabled_env_set = os.getenv("YUMI_PROACTIVE_ENABLED")
    if enabled_env_set is not None and str(enabled_env_set).strip():
        config.proactive_enabled = _env_bool("YUMI_PROACTIVE_ENABLED", config.proactive_enabled)
        if not mode_from_env:
            config.proactive_mode = "smart" if config.proactive_enabled else "off"
    else:
        config.proactive_enabled = _env_bool("YUMI_PROACTIVE_ENABLED", config.proactive_enabled)

    edge_limit = os.getenv("YUMI_EDGE_TOOLS_RETRIEVAL_LIMIT")
    if edge_limit:
        try:
            config.edge_tools_retrieval_limit = max(0, min(200, int(edge_limit.strip())))
        except ValueError:
            pass

    tg_token = os.getenv("TELEGRAM_BOT_TOKEN")
    if tg_token and tg_token.strip():
        config.telegram_bot_token = tg_token.strip()

    tg_allow = os.getenv("TELEGRAM_ALLOWED_USER_IDS")
    if tg_allow and tg_allow.strip():
        ids: list[int] = []
        for part in tg_allow.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                ids.append(int(part))
            except ValueError:
                pass
        if ids:
            config.telegram_allowed_user_ids = ids

    line_secret = os.getenv("LINE_CHANNEL_SECRET")
    if line_secret and line_secret.strip():
        config.line_channel_secret = line_secret.strip()
    line_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
    if line_token and line_token.strip():
        config.line_channel_access_token = line_token.strip()
    line_allow = os.getenv("LINE_ALLOWED_USER_IDS")
    if line_allow and line_allow.strip():
        lids = [p.strip() for p in line_allow.split(",") if p.strip()]
        if lids:
            config.line_allowed_user_ids = lids
    line_port = os.getenv("LINE_BOT_PORT")
    if line_port and line_port.strip():
        try:
            config.line_bot_port = max(1, min(65535, int(line_port.strip())))
        except ValueError:
            pass

    proactive_channels = os.getenv("YUMI_PROACTIVE_CHANNELS")
    if proactive_channels and proactive_channels.strip():
        channels = [p.strip() for p in proactive_channels.split(",") if p.strip()]
        if channels:
            config.proactive_channels = channels
    proactive_sessions = os.getenv("YUMI_PROACTIVE_SESSION_IDS")
    if proactive_sessions and proactive_sessions.strip():
        sessions = [p.strip() for p in proactive_sessions.split(",") if p.strip()]
        if sessions:
            config.proactive_session_ids = sessions
    proactive_limit = os.getenv("YUMI_PROACTIVE_DAILY_LIMIT")
    if proactive_limit and proactive_limit.strip():
        try:
            config.proactive_daily_limit = max(0, min(100, int(proactive_limit.strip())))
        except ValueError:
            pass
    proactive_quiet = os.getenv("YUMI_PROACTIVE_QUIET_HOURS")
    if proactive_quiet and proactive_quiet.strip():
        config.proactive_quiet_hours = proactive_quiet.strip()
    proactive_interval = os.getenv("YUMI_PROACTIVE_CHECK_INTERVAL_SECONDS")
    if proactive_interval and proactive_interval.strip():
        try:
            config.proactive_check_interval_seconds = max(60, min(86400, int(proactive_interval.strip())))
        except ValueError:
            pass
    proactive_idle = os.getenv("YUMI_PROACTIVE_MIN_IDLE_MINUTES")
    if proactive_idle and proactive_idle.strip():
        try:
            config.proactive_min_idle_minutes = max(1, min(10080, int(proactive_idle.strip())))
        except ValueError:
            pass
    proactive_escalation = os.getenv("YUMI_PROACTIVE_UNREPLIED_ESCALATION_MINUTES")
    if proactive_escalation and proactive_escalation.strip():
        try:
            config.proactive_unreplied_escalation_minutes = max(1, min(10080, int(proactive_escalation.strip())))
        except ValueError:
            pass
    proactive_profile = os.getenv("YUMI_PROACTIVE_PROFILE")
    if proactive_profile and proactive_profile.strip():
        config.proactive_profile = proactive_profile.strip()
    proactive_profile_prompt = os.getenv("YUMI_PROACTIVE_PROFILE_PROMPT")
    if proactive_profile_prompt and proactive_profile_prompt.strip():
        config.proactive_profile_prompt = proactive_profile_prompt.strip()
    proactive_tone = os.getenv("YUMI_PROACTIVE_TONE_INTENSITY")
    if proactive_tone and proactive_tone.strip():
        config.proactive_tone_intensity = proactive_tone.strip()
    proactive_smart_naturalness = os.getenv("YUMI_PROACTIVE_SMART_NATURALNESS")
    if proactive_smart_naturalness and proactive_smart_naturalness.strip():
        config.proactive_smart_naturalness = ModelConfig.model_validate(
            {**config.model_dump(), "proactive_smart_naturalness": proactive_smart_naturalness.strip()}
        ).proactive_smart_naturalness
    proactive_smart_max_followups = os.getenv("YUMI_PROACTIVE_SMART_MAX_UNREPLIED_FOLLOWUPS")
    if proactive_smart_max_followups and proactive_smart_max_followups.strip():
        try:
            config.proactive_smart_max_unreplied_followups = max(
                1,
                min(20, int(proactive_smart_max_followups.strip())),
            )
        except ValueError:
            pass
    local_tz = os.getenv("YUMI_LOCAL_TIMEZONE")
    if local_tz and local_tz.strip():
        config.local_timezone = local_tz.strip()
    else:
        legacy_proactive_tz = os.getenv("YUMI_PROACTIVE_QUIET_HOURS_TIMEZONE")
        if legacy_proactive_tz and legacy_proactive_tz.strip():
            config.local_timezone = legacy_proactive_tz.strip()
    proactive_jitter = os.getenv("YUMI_PROACTIVE_CHECK_INTERVAL_JITTER_RATIO")
    if proactive_jitter and proactive_jitter.strip():
        try:
            v = float(proactive_jitter.strip())
            config.proactive_check_interval_jitter_ratio = float(max(0.0, min(0.5, v)))
        except ValueError:
            pass
    proactive_esc_jitter = os.getenv("YUMI_PROACTIVE_UNREPLIED_ESCALATION_JITTER_RATIO")
    if proactive_esc_jitter and proactive_esc_jitter.strip():
        try:
            v = float(proactive_esc_jitter.strip())
            config.proactive_unreplied_escalation_jitter_ratio = float(max(0.0, min(0.5, v)))
        except ValueError:
            pass
    proactive_checkin_p = os.getenv("YUMI_PROACTIVE_CHECK_IN_PROBABILITY")
    if proactive_checkin_p and proactive_checkin_p.strip():
        try:
            v = float(proactive_checkin_p.strip())
            config.proactive_check_in_probability = float(max(0.0, min(1.0, v)))
        except ValueError:
            pass

    proactive_sched_times = os.getenv("YUMI_PROACTIVE_SCHEDULE_TIMES")
    if proactive_sched_times and proactive_sched_times.strip():
        times = [p.strip() for p in proactive_sched_times.split(",") if p.strip()]
        if times:
            try:
                config.proactive_schedule_times = ModelConfig.model_validate(
                    {**config.model_dump(), "proactive_schedule_times": times}
                ).proactive_schedule_times
            except ValidationError:
                pass
    proactive_sched_interval = os.getenv("YUMI_PROACTIVE_SCHEDULE_INTERVAL_MINUTES")
    if proactive_sched_interval and proactive_sched_interval.strip():
        try:
            iv = int(proactive_sched_interval.strip())
            if 5 <= iv <= 10_080:
                config.proactive_schedule_interval_minutes = iv
        except ValueError:
            pass
    sched_idle = os.getenv("YUMI_PROACTIVE_SCHEDULE_REQUIRE_IDLE")
    if sched_idle is not None and str(sched_idle).strip():
        config.proactive_schedule_require_idle = _env_bool(
            "YUMI_PROACTIVE_SCHEDULE_REQUIRE_IDLE",
            config.proactive_schedule_require_idle,
        )

    stt_provider = os.getenv("YUMI_STT_PROVIDER")
    if stt_provider:
        config.stt_provider = stt_provider.strip() or config.stt_provider
    stt_backend = os.getenv("YUMI_STT_BACKEND")
    if stt_backend:
        config.stt_backend = stt_backend.strip() or config.stt_backend
    stt_model = os.getenv("YUMI_STT_MODEL")
    if stt_model:
        config.stt_model = stt_model.strip() or config.stt_model
    stt_model_dir = os.getenv("YUMI_STT_MODEL_DIR")
    if stt_model_dir:
        config.stt_model_dir = stt_model_dir.strip() or config.stt_model_dir
    stt_language = os.getenv("YUMI_STT_LANGUAGE")
    if stt_language:
        config.stt_language = stt_language.strip() or config.stt_language

    config.proactive_enabled = config.proactive_mode != "off"

    return config


def save_model_config(config: ModelConfig) -> None:
    ensure_config_dir()
    payload = json.dumps(config.model_dump(), ensure_ascii=False, indent=2).encode("utf-8")
    # Atomic write with 0o600 perms — config.json holds API keys, bot tokens, and lan_secret.
    tmp_path = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(tmp_path, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
    except Exception:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise
    os.replace(tmp_path, CONFIG_PATH)
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass


def ensure_full_model_config_file() -> ModelConfig:
    """Write ~/.yumi/config.json with every known config key and current saved values."""
    config = load_saved_model_config()
    save_model_config(config)
    return config
