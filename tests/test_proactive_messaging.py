import asyncio
import random
from datetime import datetime, timedelta, timezone

from kumi.core.features.config import ModelConfig
from kumi.core.features.config.store import load_model_config
from kumi.core.features.proactive.interaction import (
    smart_followup_delay_multiplier,
    smart_interaction,
    smart_interaction_state,
)
from kumi.core.features.proactive.planner import ProactiveDecision, decide_proactive_send, in_quiet_hours
from kumi.core.features.proactive.prompt import build_proactive_prompt
from kumi.core.features.proactive.service import ProactiveMessageService
from kumi.core.features.proactive.state import ProactiveSessionState, ProactiveStateStore
from kumi.core.features.proactive.timezone_utils import format_user_facing_time
from kumi.core.features.proactive.tools import proactive_context_lines, proactive_tool_schemas
from kumi.core.tool import TOOL_REGISTRY, register_tool


def test_proactive_config_defaults_disabled():
    cfg = ModelConfig()
    assert cfg.proactive_mode == "off"
    assert cfg.proactive_enabled is False
    assert cfg.proactive_channels == ["telegram"]
    assert cfg.proactive_session_ids == []
    assert cfg.proactive_profile == "default"
    assert cfg.local_timezone is None
    assert cfg.proactive_check_interval_jitter_ratio == 0.15
    assert cfg.proactive_unreplied_escalation_jitter_ratio == 0.0
    assert cfg.proactive_check_in_probability == 0.35
    assert cfg.proactive_smart_naturalness == "balanced"
    assert cfg.proactive_smart_max_unreplied_followups == 4


def test_proactive_env_overrides(monkeypatch, tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("kumi.core.features.config.paths.CONFIG_PATH", p)
    monkeypatch.setattr("kumi.core.features.config.store.CONFIG_PATH", p)
    monkeypatch.setenv("KUMI_PROACTIVE_ENABLED", "1")
    monkeypatch.setenv("KUMI_PROACTIVE_SESSION_IDS", "tg_1,tg_2")
    monkeypatch.setenv("KUMI_PROACTIVE_PROFILE", "writing_partner")
    monkeypatch.setenv("KUMI_PROACTIVE_PROFILE_PROMPT", "Check on the draft.")
    monkeypatch.setenv("KUMI_PROACTIVE_TONE_INTENSITY", "medium")
    monkeypatch.setenv("KUMI_PROACTIVE_QUIET_HOURS_TIMEZONE", "Pacific/Auckland")
    monkeypatch.setenv("KUMI_PROACTIVE_CHECK_INTERVAL_JITTER_RATIO", "0.2")
    monkeypatch.setenv("KUMI_PROACTIVE_UNREPLIED_ESCALATION_JITTER_RATIO", "0.1")
    monkeypatch.setenv("KUMI_PROACTIVE_CHECK_IN_PROBABILITY", "0.5")
    monkeypatch.setenv("KUMI_PROACTIVE_SMART_NATURALNESS", "subtle")
    monkeypatch.setenv("KUMI_PROACTIVE_SMART_MAX_UNREPLIED_FOLLOWUPS", "6")

    cfg = load_model_config()

    assert cfg.proactive_mode == "smart"
    assert cfg.proactive_enabled is True
    assert cfg.proactive_session_ids == ["tg_1", "tg_2"]
    assert cfg.proactive_profile == "writing_partner"
    assert cfg.proactive_profile_prompt == "Check on the draft."
    assert cfg.proactive_tone_intensity == "medium"
    assert cfg.local_timezone == "Pacific/Auckland"
    assert cfg.proactive_check_interval_jitter_ratio == 0.2
    assert cfg.proactive_unreplied_escalation_jitter_ratio == 0.1
    assert cfg.proactive_check_in_probability == 0.5
    assert cfg.proactive_smart_naturalness == "subtle"
    assert cfg.proactive_smart_max_unreplied_followups == 6


def test_proactive_env_local_timezone_override_precedence(monkeypatch, tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("kumi.core.features.config.paths.CONFIG_PATH", p)
    monkeypatch.setattr("kumi.core.features.config.store.CONFIG_PATH", p)
    monkeypatch.setenv("KUMI_LOCAL_TIMEZONE", "Europe/London")
    monkeypatch.setenv("KUMI_PROACTIVE_QUIET_HOURS_TIMEZONE", "Pacific/Auckland")

    cfg = load_model_config()

    assert cfg.local_timezone == "Europe/London"


def test_proactive_legacy_json_enabled_derives_smart():
    cfg = ModelConfig.model_validate({"proactive_enabled": True})
    assert cfg.proactive_mode == "smart"
    assert cfg.proactive_enabled is True


def test_proactive_legacy_json_disabled_derives_off():
    cfg = ModelConfig.model_validate({"proactive_enabled": False})
    assert cfg.proactive_mode == "off"


def test_proactive_mode_off_never_sends():
    cfg = ModelConfig(
        proactive_mode="off",
        proactive_quiet_hours="",
        proactive_min_idle_minutes=1,
    )
    now = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)
    state = ProactiveSessionState("tg_1")
    assert decide_proactive_send(cfg, state, now=now).reason == "disabled"


def test_proactive_scheduled_time_window():
    cfg = ModelConfig(
        proactive_mode="scheduled",
        proactive_schedule_times=["12:00"],
        proactive_quiet_hours="",
        proactive_daily_limit=4,
        proactive_min_idle_minutes=1,
        local_timezone="UTC",
        proactive_check_interval_seconds=900,
    )
    now = datetime(2026, 5, 3, 12, 5, tzinfo=timezone.utc)
    state = ProactiveSessionState(
        "tg_1",
        last_proactive_at=(now - timedelta(hours=2)).isoformat(),
        last_user_message_at=(now - timedelta(hours=2)).isoformat(),
    )
    d = decide_proactive_send(cfg, state, now=now)
    assert d.should_send is True
    assert d.trigger == "scheduled_time"
    assert d.scheduled_slot_key == "2026-05-03 12:00"


def test_proactive_scheduled_slot_dedupe():
    cfg = ModelConfig(
        proactive_mode="scheduled",
        proactive_schedule_times=["12:00"],
        proactive_quiet_hours="",
        proactive_daily_limit=4,
        proactive_min_idle_minutes=1,
        local_timezone="UTC",
        proactive_check_interval_seconds=900,
    )
    now = datetime(2026, 5, 3, 12, 5, tzinfo=timezone.utc)
    state = ProactiveSessionState(
        "tg_1",
        last_proactive_at=(now - timedelta(hours=2)).isoformat(),
        last_user_message_at=(now - timedelta(hours=2)).isoformat(),
        last_scheduled_slot="2026-05-03 12:00",
    )
    assert decide_proactive_send(cfg, state, now=now).should_send is False


def test_proactive_scheduled_interval():
    cfg = ModelConfig(
        proactive_mode="scheduled",
        proactive_schedule_interval_minutes=60,
        proactive_quiet_hours="",
        proactive_daily_limit=4,
        proactive_min_idle_minutes=1,
        local_timezone="UTC",
    )
    now = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)
    state = ProactiveSessionState("tg_1", last_scheduled_interval_at=(now - timedelta(minutes=30)).isoformat())
    assert decide_proactive_send(cfg, state, now=now).should_send is False

    state2 = ProactiveSessionState(
        "tg_1",
        last_scheduled_interval_at=(now - timedelta(minutes=61)).isoformat(),
    )
    d = decide_proactive_send(cfg, state2, now=now)
    assert d.should_send is True
    assert d.mark_scheduled_interval is True


def test_proactive_scheduled_respects_quiet_hours():
    cfg = ModelConfig(
        proactive_mode="scheduled",
        proactive_schedule_times=["12:00"],
        proactive_quiet_hours="11:00-13:00",
        proactive_daily_limit=4,
        proactive_min_idle_minutes=1,
        local_timezone="UTC",
        proactive_check_interval_seconds=900,
    )
    now = datetime(2026, 5, 3, 12, 5, tzinfo=timezone.utc)
    state = ProactiveSessionState(
        "tg_1",
        last_proactive_at=(now - timedelta(hours=2)).isoformat(),
        last_user_message_at=(now - timedelta(hours=2)).isoformat(),
    )
    assert decide_proactive_send(cfg, state, now=now).reason == "quiet_hours"


def test_proactive_scheduled_does_not_use_unreplied_escalation():
    cfg = ModelConfig(
        proactive_mode="scheduled",
        proactive_schedule_times=["12:00"],
        proactive_quiet_hours="",
        proactive_daily_limit=4,
        proactive_min_idle_minutes=1,
        local_timezone="UTC",
        proactive_check_interval_seconds=900,
        proactive_unreplied_escalation_minutes=1000,
    )
    now = datetime(2026, 5, 3, 12, 2, tzinfo=timezone.utc)
    state = ProactiveSessionState(
        "tg_1",
        unreplied_count=3,
        last_proactive_at=(now - timedelta(minutes=5)).isoformat(),
        last_user_message_at=(now - timedelta(hours=2)).isoformat(),
    )
    # Smart mode would hit waiting_before_unreplied_followup; scheduled still allows window.
    d = decide_proactive_send(cfg, state, now=now)
    assert d.should_send is True


def test_proactive_env_mode_scheduled(monkeypatch, tmp_path):
    p = tmp_path / "config.json"
    p.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("kumi.core.features.config.paths.CONFIG_PATH", p)
    monkeypatch.setattr("kumi.core.features.config.store.CONFIG_PATH", p)
    monkeypatch.setenv("KUMI_PROACTIVE_MODE", "scheduled")
    monkeypatch.setenv("KUMI_PROACTIVE_SCHEDULE_TIMES", "08:00,20:00")
    monkeypatch.setenv("KUMI_PROACTIVE_SCHEDULE_INTERVAL_MINUTES", "120")
    monkeypatch.setenv("KUMI_PROACTIVE_SCHEDULE_REQUIRE_IDLE", "0")

    cfg = load_model_config()
    assert cfg.proactive_mode == "scheduled"
    assert cfg.proactive_enabled is True
    assert cfg.proactive_schedule_times == ["08:00", "20:00"]
    assert cfg.proactive_schedule_interval_minutes == 120
    assert cfg.proactive_schedule_require_idle is False


def test_proactive_planner_respects_quiet_hours_and_limits():
    cfg = ModelConfig(proactive_enabled=True, proactive_daily_limit=1, proactive_quiet_hours="00:30-08:30")
    quiet_now = datetime(2026, 5, 3, 1, 0, tzinfo=timezone.utc)
    assert in_quiet_hours(quiet_now, cfg.proactive_quiet_hours) is True
    assert decide_proactive_send(cfg, ProactiveSessionState("tg_1"), now=quiet_now).reason == "quiet_hours"

    active_now = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)
    state = ProactiveSessionState("tg_1", date="2026-05-03", sent_today=1)
    assert decide_proactive_send(cfg, state, now=active_now).reason == "daily_limit"


def test_format_user_facing_time_uses_iana_when_configured():
    now = datetime(2026, 5, 3, 4, 46, tzinfo=timezone.utc)
    s = format_user_facing_time(now, "Pacific/Auckland")
    assert "2026-05-03 16:46:00" in s


def test_proactive_quiet_hours_uses_configured_timezone():
    utc_moment = datetime(2026, 5, 3, 14, 0, tzinfo=timezone.utc)
    assert in_quiet_hours(utc_moment, "00:30-08:30", None) is False
    assert in_quiet_hours(utc_moment, "00:30-08:30", "Pacific/Auckland") is True


def test_proactive_daily_limit_calendar_follows_timezone():
    cfg = ModelConfig(
        proactive_enabled=True,
        proactive_daily_limit=1,
        proactive_quiet_hours="",
        local_timezone="Pacific/Auckland",
    )
    now = datetime(2026, 5, 3, 14, 0, tzinfo=timezone.utc)
    state = ProactiveSessionState("tg_1", date="2026-05-04", sent_today=1)
    assert decide_proactive_send(cfg, state, now=now).reason == "daily_limit"


def test_proactive_unreplied_escalation_jitter_is_deterministic_per_state():
    cfg = ModelConfig(
        proactive_enabled=True,
        proactive_quiet_hours="",
        proactive_min_idle_minutes=1,
        proactive_unreplied_escalation_minutes=60,
        proactive_unreplied_escalation_jitter_ratio=0.25,
    )
    now = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)
    last_p = (now - timedelta(minutes=50)).isoformat()
    state = ProactiveSessionState("tg_1", last_proactive_at=last_p, unreplied_count=1)
    a = decide_proactive_send(cfg, state, now=now, rng=random.Random(1))
    b = decide_proactive_send(cfg, state, now=now, rng=random.Random(999))
    assert a.should_send == b.should_send
    assert a.reason == b.reason


def test_proactive_check_in_respects_configured_probability():
    cfg = ModelConfig(
        proactive_enabled=True,
        proactive_quiet_hours="",
        proactive_min_idle_minutes=1,
        proactive_check_in_probability=0.0,
    )
    now = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)
    state = ProactiveSessionState(
        "tg_1",
        last_proactive_at=(now - timedelta(minutes=120)).isoformat(),
        last_user_message_at=(now - timedelta(minutes=120)).isoformat(),
        unreplied_count=0,
    )
    decision = decide_proactive_send(cfg, state, now=now, rng=random.Random(42))
    assert decision.should_send is False
    assert decision.reason == "random_skip"


def test_proactive_planner_unreplied_followup():
    cfg = ModelConfig(
        proactive_enabled=True,
        proactive_quiet_hours="",
        proactive_min_idle_minutes=10,
        proactive_unreplied_escalation_minutes=30,
    )
    now = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)
    state = ProactiveSessionState(
        "tg_1",
        date="2026-05-03",
        last_proactive_at=(now - timedelta(minutes=31)).isoformat(),
        unreplied_count=1,
    )

    decision = decide_proactive_send(cfg, state, now=now)

    assert decision.should_send is True
    assert decision.trigger == "unreplied_followup"


def test_smart_interaction_states_are_role_neutral():
    assert smart_interaction_state(ProactiveSessionState("tg_1", unreplied_count=0)) == "casual"
    assert smart_interaction_state(ProactiveSessionState("tg_1", unreplied_count=1)) == "waiting"
    assert smart_interaction_state(ProactiveSessionState("tg_1", unreplied_count=2)) == "light_nudge"
    assert smart_interaction_state(ProactiveSessionState("tg_1", unreplied_count=3)) == "reserved"
    assert smart_interaction_state(ProactiveSessionState("tg_1", unreplied_count=4)) == "give_space"

    interaction = smart_interaction(
        ModelConfig(proactive_mode="smart"),
        ProactiveSessionState("tg_1", unreplied_count=2),
        trigger="unreplied_followup",
    )
    assert interaction.state == "light_nudge"
    assert "system prompt" in interaction.style_guidance
    assert "girlfriend" not in interaction.style_guidance.lower()


def test_smart_unreplied_followups_slow_down_and_then_give_space():
    cfg = ModelConfig(
        proactive_mode="smart",
        proactive_quiet_hours="",
        proactive_min_idle_minutes=1,
        proactive_unreplied_escalation_minutes=30,
        proactive_smart_max_unreplied_followups=4,
    )
    now = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)
    state = ProactiveSessionState(
        "tg_1",
        last_proactive_at=(now - timedelta(minutes=45)).isoformat(),
        unreplied_count=2,
    )

    assert smart_followup_delay_multiplier(state) == 1.75
    waiting = decide_proactive_send(cfg, state, now=now)
    assert waiting.should_send is False
    assert waiting.reason == "waiting_before_unreplied_followup"

    state.last_proactive_at = (now - timedelta(minutes=53)).isoformat()
    ready = decide_proactive_send(cfg, state, now=now)
    assert ready.should_send is True
    assert ready.trigger == "unreplied_followup"

    give_space = ProactiveSessionState(
        "tg_1",
        last_proactive_at=(now - timedelta(minutes=500)).isoformat(),
        unreplied_count=4,
    )
    skipped = decide_proactive_send(cfg, give_space, now=now)
    assert skipped.should_send is False
    assert skipped.reason == "give_space_after_unreplied_followups"


def test_smart_naturalness_off_keeps_legacy_unreplied_interval():
    cfg = ModelConfig(
        proactive_mode="smart",
        proactive_quiet_hours="",
        proactive_min_idle_minutes=1,
        proactive_unreplied_escalation_minutes=30,
        proactive_smart_naturalness="off",
    )
    now = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)
    state = ProactiveSessionState(
        "tg_1",
        last_proactive_at=(now - timedelta(minutes=31)).isoformat(),
        unreplied_count=3,
    )

    decision = decide_proactive_send(cfg, state, now=now)
    assert decision.should_send is True
    assert decision.trigger == "unreplied_followup"


def test_proactive_tool_policy_and_context(monkeypatch):
    TOOL_REGISTRY.clear()

    def status() -> str:
        return "all good"

    def hidden() -> str:
        return "hidden"

    register_tool(status, "Read status", allow_proactive=True, proactive_context=True)
    register_tool(hidden, "Hidden")

    assert [t["function"]["name"] for t in proactive_tool_schemas()] == ["status"]

    lines = asyncio.run(proactive_context_lines())
    assert lines == ["status: all good"]


def test_proactive_prompt_always_includes_current_time_context():
    now = datetime(2026, 5, 3, 12, 30, tzinfo=timezone.utc)
    prompt = build_proactive_prompt(
        ModelConfig(),
        ProactiveSessionState("tg_1"),
        decision=ProactiveDecision(True, trigger="check_in", reason="test"),
        now=now,
        context_lines=[],
    )

    assert "[Proactive Context]" in prompt
    expected = format_user_facing_time(now, None)
    assert f"- Current time: {expected}" in prompt


def test_proactive_prompt_adds_smart_style_only_for_smart_mode():
    now = datetime(2026, 5, 3, 12, 30, tzinfo=timezone.utc)
    smart_prompt = build_proactive_prompt(
        ModelConfig(proactive_mode="smart"),
        ProactiveSessionState("tg_1", unreplied_count=2),
        decision=ProactiveDecision(True, trigger="unreplied_followup", reason="test"),
        now=now,
        context_lines=[],
    )

    assert "[Smart Proactive Style]" in smart_prompt
    assert "Interaction state: light_nudge" in smart_prompt
    assert "Do not assume a romantic or companion role" in smart_prompt
    assert "girlfriend" not in smart_prompt.lower()

    scheduled_prompt = build_proactive_prompt(
        ModelConfig(proactive_mode="scheduled"),
        ProactiveSessionState("tg_1", unreplied_count=2),
        decision=ProactiveDecision(True, trigger="scheduled_time", reason="test"),
        now=now,
        context_lines=[],
    )
    assert "[Smart Proactive Style]" not in scheduled_prompt


def test_proactive_service_sends_and_records(monkeypatch, tmp_path):
    p_cfg = tmp_path / "kumi_config.json"
    p_cfg.write_text("{}", encoding="utf-8")
    monkeypatch.setattr("kumi.core.features.config.paths.CONFIG_PATH", p_cfg)
    monkeypatch.setattr("kumi.core.features.config.store.CONFIG_PATH", p_cfg)

    class FakeMemory:
        def __init__(self):
            self.added = []

        def get_context(self, query=None):
            return [{"role": "system", "content": "Be concise."}]

        def add_message(self, role, content, thought=None):
            self.added.append((role, content))

    class FakeProvider:
        async def chat_stream(self, **_kwargs):
            yield {"type": "text", "content": "<msg>Hello there</msg><msg>Small check-in</msg>"}

    class FakeBot:
        def __init__(self):
            self.provider = FakeProvider()
            self.model_name = "fake"
            self.memory = FakeMemory()

        def session_memory(self, session_id):
            return self.memory

    sent = []

    async def fake_send(session_id, text, prefix=""):
        sent.append((session_id, text, prefix))
        return True

    monkeypatch.setattr("kumi.telegram.notify.send_text_to_telegram", fake_send)
    store = ProactiveStateStore(tmp_path / "state.json")
    now = datetime.now(timezone.utc)
    store.put(
        ProactiveSessionState(
            "tg_1",
            date=now.date().isoformat(),
            last_proactive_at=(now - timedelta(minutes=200)).isoformat(),
            unreplied_count=1,
        )
    )
    cfg = ModelConfig(
        proactive_enabled=True,
        proactive_session_ids=["tg_1"],
        proactive_quiet_hours="",
        proactive_min_idle_minutes=1,
        proactive_unreplied_escalation_minutes=30,
    )

    asyncio.run(ProactiveMessageService(FakeBot(), state_store=store)._maybe_send_for_session("tg_1", cfg=cfg))

    assert sent == [("tg_1", "Hello there", ""), ("tg_1", "Small check-in", "")]
    assert store.get("tg_1").sent_today == 1


def test_legacy_json_derives_proactive_mode_from_enabled():
    cfg = ModelConfig.model_validate({"proactive_enabled": True})
    assert cfg.proactive_mode == "smart"
    assert cfg.proactive_enabled is True
    cfg2 = ModelConfig.model_validate({"proactive_enabled": False})
    assert cfg2.proactive_mode == "off"
    assert cfg2.proactive_enabled is False


def test_scheduled_fixed_time_triggers_in_grace_window():
    cfg = ModelConfig(
        proactive_mode="scheduled",
        proactive_schedule_times=["12:00"],
        proactive_quiet_hours="",
        proactive_min_idle_minutes=1,
        proactive_check_interval_seconds=900,
        local_timezone="UTC",
    )
    now = datetime(2026, 5, 3, 12, 5, tzinfo=timezone.utc)
    state = ProactiveSessionState(
        "tg_1",
        date="2026-05-03",
        last_proactive_at=(now - timedelta(hours=2)).isoformat(),
        last_user_message_at=(now - timedelta(hours=2)).isoformat(),
    )
    d = decide_proactive_send(cfg, state, now=now)
    assert d.should_send is True
    assert d.trigger == "scheduled_time"
    assert d.scheduled_slot_key == "2026-05-03 12:00"


def test_scheduled_same_slot_not_sent_twice():
    cfg = ModelConfig(
        proactive_mode="scheduled",
        proactive_schedule_times=["12:00"],
        proactive_quiet_hours="",
        proactive_min_idle_minutes=1,
        local_timezone="UTC",
    )
    now = datetime(2026, 5, 3, 12, 3, tzinfo=timezone.utc)
    state = ProactiveSessionState(
        "tg_1",
        date="2026-05-03",
        last_proactive_at=(now - timedelta(hours=2)).isoformat(),
        last_user_message_at=(now - timedelta(hours=2)).isoformat(),
        last_scheduled_slot="2026-05-03 12:00",
    )
    d = decide_proactive_send(cfg, state, now=now)
    assert d.should_send is False
    assert d.reason == "scheduled_no_match"


def test_scheduled_interval_first_fire():
    cfg = ModelConfig(
        proactive_mode="scheduled",
        proactive_schedule_interval_minutes=60,
        proactive_quiet_hours="",
        proactive_schedule_require_idle=False,
        local_timezone="UTC",
    )
    now = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)
    state = ProactiveSessionState("tg_1", date="2026-05-03")
    d = decide_proactive_send(cfg, state, now=now)
    assert d.should_send is True
    assert d.trigger == "scheduled_interval"
    assert d.mark_scheduled_interval is True


def test_scheduled_respects_quiet_hours():
    cfg = ModelConfig(
        proactive_mode="scheduled",
        proactive_schedule_times=["12:00"],
        proactive_quiet_hours="11:00-13:00",
        proactive_min_idle_minutes=1,
        local_timezone="UTC",
    )
    now = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)
    state = ProactiveSessionState(
        "tg_1",
        date="2026-05-03",
        last_proactive_at=(now - timedelta(hours=2)).isoformat(),
        last_user_message_at=(now - timedelta(hours=2)).isoformat(),
    )
    d = decide_proactive_send(cfg, state, now=now)
    assert d.should_send is False
    assert d.reason == "quiet_hours"


def test_scheduled_unreplied_does_not_trigger_smart_followup():
    cfg = ModelConfig(
        proactive_mode="scheduled",
        proactive_schedule_times=["15:00"],
        proactive_quiet_hours="",
        proactive_min_idle_minutes=1,
        local_timezone="UTC",
    )
    now = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)
    state = ProactiveSessionState(
        "tg_1",
        unreplied_count=5,
        last_proactive_at=(now - timedelta(minutes=500)).isoformat(),
        last_user_message_at=(now - timedelta(minutes=500)).isoformat(),
    )
    d = decide_proactive_send(cfg, state, now=now)
    assert d.should_send is False
    assert d.reason == "scheduled_no_match"


def test_scheduled_not_configured_when_empty():
    cfg = ModelConfig(
        proactive_mode="scheduled",
        proactive_quiet_hours="",
        local_timezone="UTC",
    )
    now = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)
    d = decide_proactive_send(cfg, ProactiveSessionState("tg_1"), now=now)
    assert d.should_send is False
    assert d.reason == "scheduled_not_configured"


def test_record_sent_updates_scheduled_dedupe_fields(monkeypatch, tmp_path):
    p_cfg = tmp_path / "kumi_config.json"
    p_cfg.write_text('{"local_timezone": "UTC"}', encoding="utf-8")
    monkeypatch.setattr("kumi.core.features.config.paths.CONFIG_PATH", p_cfg)
    monkeypatch.setattr("kumi.core.features.config.store.CONFIG_PATH", p_cfg)

    store = ProactiveStateStore(tmp_path / "st.json")
    now = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)
    store.record_sent(
        "tg_1",
        trigger="scheduled_time",
        at=now,
        scheduled_slot_key="2026-05-03 12:00",
        mark_scheduled_interval=True,
    )
    st = store.get("tg_1")
    assert st.last_scheduled_slot == "2026-05-03 12:00"
    assert st.last_scheduled_interval_at is not None
