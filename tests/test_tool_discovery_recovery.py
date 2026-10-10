"""Music discovery regressions: first-turn recall, outage recovery and scoped paging."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from yumi.core.features.config import ModelConfig
from yumi.core.platform.plugins import LOCAL_IDENTITY
from yumi.core.platform.providers.budget import token_estimate
from yumi.core.platform.runtime import RuntimeState
from yumi.core.platform.tools import retrieval, routing
from yumi.tools import edge_discovery_tools as discovery

DEVICE = "RoomMusicMacMini"
SEARCH = f"edge_{DEVICE}__music_search"
PLAY = f"edge_{DEVICE}__music_play"


def schema(name, description="", params=None):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {k: {"type": "string", "description": v} for k, v in (params or {}).items()},
            },
        },
    }


@pytest.fixture
def setup(monkeypatch, tmp_path):
    from collections import OrderedDict

    from yumi.core.platform.tools import session_tools, tool
    from yumi.tools.bootstrap import init_yumi

    monkeypatch.setattr("yumi.core.features.config.paths.CONFIG_DIR", tmp_path)
    monkeypatch.setattr(session_tools, "_RECENT", OrderedDict())
    registry = {}
    monkeypatch.setattr(tool, "TOOL_REGISTRY", registry)
    monkeypatch.setattr(routing, "TOOL_REGISTRY", registry)
    init_yumi()
    runtime = RuntimeState()
    specs = json.loads((Path(__file__).parent / "fixtures/room_music_tools.json").read_text())
    runtime.edge_registry.tools[DEVICE] = {
        f"edge_{DEVICE}__{s['name']}": {"schema": schema(f"edge_{DEVICE}__{s['name']}", s["description"], s["params"])}
        for s in specs
    }
    runtime.edge_registry.active_connections[DEVICE] = object()
    cfg = ModelConfig(edge_tools_routing_mode="on_demand", embedding_model=None)
    monkeypatch.setattr(routing, "load_model_config", lambda: cfg)
    monkeypatch.setattr("yumi.core.features.config.load_model_config", lambda: cfg)
    monkeypatch.setattr(discovery, "get_default_runtime", lambda: runtime)
    monkeypatch.setattr(discovery, "get_current_identity", lambda: LOCAL_IDENTITY)
    return runtime, cfg


def select(runtime, query, disabled=None):
    return routing.select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query=query,
        session_id="music-regression",
        disabled_tools=disabled or set(),
        edge_registry=runtime.edge_registry.tools,
    )


def add_noise(runtime, count=300):
    runtime.edge_registry.tools["factory"] = {
        f"edge_factory__machine_{i}": {
            "schema": schema(f"edge_factory__machine_{i}", "Calibrate industrial pressure sensors " * 8)
        }
        for i in range(count)
    }


def test_actual_twelve_music_tools_fit_first_request_without_search(setup, monkeypatch):
    runtime, cfg = setup
    monkeypatch.setattr(retrieval, "rank_tools", lambda *a, **k: pytest.fail("small catalog should bypass retrieval"))
    decision = select(runtime, "我想听yoasobe 的夜に駆ける")
    assert decision.retrieval_mode == "full_catalog"
    assert {e.name for e in decision.selected_edge_tools} == set(runtime.edge_registry.tools[DEVICE])
    assert token_estimate(decision.tools) <= cfg.tool_schema_token_budget
    assert {"browse_app_tools", "discover_app_tools"} <= {s["function"]["name"] for s in decision.tools}


@pytest.mark.parametrize(
    "query",
    [
        "我想听yoasobe 的夜に駆ける",
        "播放音乐",
        "想聽 YOASOBI 的歌",
        "YOASOBI の音楽を聴きたい",
        "それ、夜にかけるを聞きたい。",
        "play music by yoasobe",
        "RoomMusicMacMini 播放音乐",
    ],
)
@pytest.mark.parametrize("count", [30, 300])
def test_music_chain_survives_large_catalog_in_multiple_languages(setup, query, count):
    runtime, cfg = setup
    add_noise(runtime, count)
    decision = select(runtime, query)
    names = {e.name for e in decision.selected_edge_tools}
    assert {SEARCH, PLAY} <= names
    assert token_estimate(decision.tools) <= cfg.tool_schema_token_budget
    assert not any("factory" in name for name in names)
    assert decision.retrieval_mode == "lexical"


def test_greeting_does_not_fill_budget_with_unrelated_large_catalog(setup):
    runtime, _ = setup
    add_noise(runtime)
    assert not select(runtime, "hello how are you").selected_edge_tools


def test_embedding_outage_is_explicit_and_catalog_still_works(setup, monkeypatch):
    runtime, cfg = setup
    cfg.embedding_model = "test-embedding"
    monkeypatch.setattr(retrieval, "_cached_embedding", lambda *a, **k: None)
    add_noise(runtime)
    decision = select(runtime, "播放音乐")
    assert decision.retrieval_degraded
    assert {SEARCH, PLAY} <= {e.name for e in decision.selected_edge_tools}
    result = json.loads(discovery.discover_app_tools("zxqv nonexistent capability"))
    assert result["status"] == "no_match"
    assert result["retrieval_degraded"]
    assert "not proof" in result["note"]
    page = json.loads(discovery.browse_app_tools(DEVICE, limit=20))
    assert {SEARCH, PLAY} <= set(page["activated_tool_names"])


def test_semantic_and_lexical_candidates_are_both_kept(setup, monkeypatch):
    runtime, _ = setup
    entries = routing.ToolCatalog(disabled_tools=set(), edge_registry=runtime.edge_registry.tools).edge_tools()

    def embed(model, text, **kwargs):
        if not kwargs.get("persistent"):
            return [1, 0]
        return [1, 0] if "Tool name: " + SEARCH + "\n" in text else [0, 1]

    monkeypatch.setattr(retrieval, "_cached_embedding", embed)
    ranked = retrieval.rank_tools(PLAY, entries, embed_model="test")
    assert ranked.matches[0][1].name == PLAY
    assert SEARCH in {e.name for _, e in ranked.matches}
    assert not ranked.degraded


def test_first_turn_never_builds_missing_remote_tool_vectors(setup, monkeypatch):
    runtime, cfg = setup
    cfg.embedding_model = "test-cold-index"
    add_noise(runtime, 100)
    calls = []

    class Provider:
        def embed(self, model, text):
            calls.append(text)
            return [1.0, 0.0]

    monkeypatch.setattr(routing, "get_embed_provider", lambda: Provider())
    decision = select(runtime, "播放音乐")
    assert decision.retrieval_degraded
    assert calls == []  # No remote request when no indexed documents can be ranked.
    assert decision.retrieval_degraded_reason == "index_incomplete"
    assert {SEARCH, PLAY} <= {e.name for e in decision.selected_edge_tools}


def test_browse_all_function_pages_without_duplicates_and_detect_catalog_change(setup):
    runtime, _ = setup
    devices = json.loads(discovery.browse_app_tools(limit=1))
    seen_devices = []
    while True:
        seen_devices += devices["devices"]
        if devices["next_offset"] is None:
            break
        devices = json.loads(
            discovery.browse_app_tools(
                offset=devices["next_offset"], limit=1, catalog_revision=devices["catalog_revision"]
            )
        )
    device = next(d for d in seen_devices if d["device"] == DEVICE)
    page = json.loads(discovery.browse_app_tools(device["device_id"], limit=3))
    seen = []
    while True:
        seen += [m["name"] for m in page["matches"]]
        assert page["activated_tool_names"] == [m["name"] for m in page["matches"]]
        if page["next_offset"] is None:
            break
        page = json.loads(
            discovery.browse_app_tools(
                device["device_id"], offset=page["next_offset"], limit=3, catalog_revision=page["catalog_revision"]
            )
        )
    assert len(seen) == len(set(seen)) == 12
    assert set(seen) == set(runtime.edge_registry.tools[DEVICE])
    runtime.tool_policy.disabled_tools.add(PLAY)
    changed = json.loads(discovery.browse_app_tools(device["device_id"], catalog_revision=page["catalog_revision"]))
    assert changed["status"] == "catalog_changed"
    fresh = json.loads(discovery.browse_app_tools(device["device_id"], limit=20))
    assert PLAY not in json.dumps(fresh)


def test_browse_scope_hides_other_accounts_and_never_uses_provided_device_as_auth(setup, monkeypatch):
    runtime, _ = setup
    secret = "edge_private__secret"
    runtime.edge_registry.tools["u:bob::private"] = {secret: {"schema": schema(secret, "Bob private device")}}

    class Scope:
        def filter_edge_tool_schemas(self, identity, registry, disabled):
            return [
                v["schema"]
                for k, tools in registry.items()
                if k == DEVICE
                for n, v in tools.items()
                if n not in disabled
            ]

    monkeypatch.setattr(routing, "get_edge_scope", lambda: Scope())
    runtime.tool_policy.disabled_tools.add(PLAY)
    for response in [
        discovery.browse_app_tools(),
        discovery.browse_app_tools(DEVICE, limit=20),
        discovery.discover_app_tools("music"),
    ]:
        assert secret not in response and "bob" not in response and PLAY not in response
    unavailable = json.loads(discovery.browse_app_tools("u:bob::private"))
    assert unavailable["status"] == "device_not_visible"


def test_budget_exclusion_is_distinct_and_does_not_hide_directory_entry(setup):
    runtime, cfg = setup
    cfg.tool_schema_token_budget = 1000
    runtime.edge_registry.tools[DEVICE] = {PLAY: {"schema": schema(PLAY, "play music " * 2000)}}
    found = json.loads(discovery.discover_app_tools(PLAY))
    assert found["status"] == "schema_budget_exceeded"
    assert found["activated_tool_names"] == []
    assert found["budget_excluded_tool_names"] == [PLAY]
    page = json.loads(discovery.browse_app_tools(DEVICE, limit=1))
    assert page["matches"][0]["name"] == PLAY
    assert not page["activated_tool_names"]
    assert page["next_offset"] is None


def test_companions_only_follow_visible_same_device_exact_references(setup):
    runtime, _ = setup
    runtime.tool_policy.disabled_tools.add(SEARCH)
    entries = discovery._catalog()
    play = next(e for e in entries if e.name == PLAY)
    assert [e.name for e in retrieval.with_companions([play], entries)] == [PLAY]


def test_offline_and_revoked_during_search(setup, monkeypatch):
    runtime, _ = setup
    runtime.edge_registry.active_connections.clear()
    page = json.loads(discovery.browse_app_tools(DEVICE, limit=20))
    assert all(not m["online"] for m in page["matches"])
    original = retrieval.rank_tools

    def revoke(*args, **kwargs):
        result = original(*args, **kwargs)
        runtime.tool_policy.disabled_tools.update({SEARCH, PLAY})
        return result

    monkeypatch.setattr(retrieval, "rank_tools", revoke)
    result = discovery.discover_app_tools("play music")
    assert SEARCH not in result and PLAY not in result


def test_browse_personal_denials_apply_to_metadata_and_activation(setup, monkeypatch):
    from yumi.core.platform.runtime.assistant_context import conversation_session

    runtime, _ = setup
    monkeypatch.setattr(
        "yumi.core.platform.plugins.get_session_scope",
        lambda: SimpleNamespace(owner_user_from_session_id=lambda sid: "alice"),
    )
    monkeypatch.setattr(
        "yumi.core.platform.runtime.assistant_context.personal_store",
        lambda owner: SimpleNamespace(get=lambda *a: {PLAY: {"ai_access": "none"}, SEARCH: {"disabled": True}}),
    )
    token = conversation_session.set("u_alice__personal_1")
    try:
        result = discovery.browse_app_tools(DEVICE, limit=20)
        assert SEARCH not in result and PLAY not in result
    finally:
        conversation_session.reset(token)


def test_provider_initialization_failure_preserves_keyword_search(setup, monkeypatch):
    runtime, cfg = setup
    cfg.embedding_model = "broken-provider"
    add_noise(runtime)

    def fail(*a, **k):
        raise RuntimeError("provider configuration unavailable")

    monkeypatch.setattr(retrieval, "_cached_embedding", fail)
    decision = select(runtime, "播放音乐")
    assert decision.retrieval_degraded
    assert {SEARCH, PLAY} <= {e.name for e in decision.selected_edge_tools}


def test_registration_burst_indexes_every_device_and_core(setup, monkeypatch):
    import asyncio

    from yumi.core.platform.tools import indexing

    _, cfg = setup
    cfg.embedding_model = "test"
    monkeypatch.setattr(routing, "get_embed_provider", lambda: object())
    monkeypatch.setattr(indexing, "_TASKS", set())
    monkeypatch.setattr(indexing, "_PENDING", {})
    warmed = []
    monkeypatch.setattr(indexing, "_warm", lambda key, registry, model: warmed.append((key, registry)))

    async def run():
        for key in [None, "a", "b", "c", "d"]:
            indexing.schedule_tool_index(key, {"version": 1})
        indexing.schedule_tool_index("a", {"version": 2})
        await asyncio.gather(*list(indexing._TASKS))

    asyncio.run(run())
    assert dict(warmed) == {
        None: {"version": 1},
        "a": {"version": 2},
        "b": {"version": 1},
        "c": {"version": 1},
        "d": {"version": 1},
    }


def test_core_index_uses_identical_search_documents(setup, monkeypatch):
    from yumi.core.platform.tools import indexing

    texts = []
    monkeypatch.setattr(routing, "_cached_embedding", lambda model, text, **kw: texts.append(text))
    indexing._warm(None, routing.TOOL_REGISTRY, "test")
    entries = routing.ToolCatalog(disabled_tools=set(), edge_registry={}).core_tools()
    assert {e.search_text for e in entries} <= set(texts)


def test_slow_semantics_preserves_music_chain_with_bounded_wait(setup, monkeypatch):
    import threading
    import time

    runtime, cfg = setup
    cfg.embedding_model = "slow"
    add_noise(runtime, 30)
    release = threading.Event()
    started = threading.Event()
    finished = threading.Event()

    def slow_query(model, text, **kwargs):
        if kwargs.get("persistent"):
            return [1.0, 0.0]
        started.set()
        release.wait(3)
        finished.set()
        return [1.0, 0.0]

    monkeypatch.setattr(retrieval, "_cached_embedding", slow_query)
    try:
        before = time.monotonic()
        decision = select(runtime, "我想听 aimyon 的 naked heart")
        elapsed = time.monotonic() - before
        assert started.is_set()
        assert elapsed < 1.15  # 750 ms retrieval budget, generous CI scheduling margin.
        assert not finished.is_set()  # The route did not wait for provider completion.
        assert decision.retrieval_degraded_reason == "timeout"
        assert {SEARCH, PLAY} <= {e.name for e in decision.selected_edge_tools}
    finally:
        release.set()
        assert finished.wait(1)


def test_saturated_semantic_workers_do_not_queue_more_requests(setup, monkeypatch):
    import threading
    import time

    runtime, _ = setup
    entries = discovery._catalog()
    release = threading.Event()
    finished = threading.Event()
    calls = []
    monkeypatch.setattr(retrieval, "_SEMANTIC_SLOTS", threading.BoundedSemaphore(1))

    def blocked(model, text, **kwargs):
        if kwargs.get("persistent"):
            return [1.0, 0.0]
        calls.append(text)
        release.wait(3)
        finished.set()
        return [1.0, 0.0]

    monkeypatch.setattr(retrieval, "_cached_embedding", blocked)
    try:
        first = retrieval.rank_tools("play music", entries, embed_model="slow", semantic_budget=0.05)
        assert first.degraded_reason == "timeout"
        before = time.monotonic()
        second = retrieval.rank_tools("播放音乐", entries, embed_model="slow")
        assert time.monotonic() - before < 0.2
        assert second.degraded_reason == "busy"
        assert calls == ["play music"]
        assert {SEARCH, PLAY} <= {e.name for _, e in second.matches}
    finally:
        release.set()
        assert finished.wait(1)


def test_semantic_worker_preserves_account_context_and_query_cache(setup, monkeypatch):
    from yumi.core.platform.runtime.embedding_cache import RequestEmbeddingCache, request_embedding_cache
    from yumi.core.platform.runtime.usage_context import usage_owner_id

    entries = discovery._catalog()
    calls = []

    class Provider:
        def embed(self, model, text):
            calls.append((usage_owner_id.get(), text))
            return [1.0, 0.0]

    provider = Provider()
    monkeypatch.setattr(routing, "get_embed_provider", lambda: provider)
    original = retrieval._cached_embedding
    monkeypatch.setattr(
        retrieval,
        "_cached_embedding",
        lambda model, text, **kw: [1.0, 0.0] if kw.get("persistent") else original(model, text, **kw),
    )
    cache = RequestEmbeddingCache()
    token = request_embedding_cache.set(cache)
    owner_token = usage_owner_id.set("alice")
    try:
        for _ in range(2):
            result = retrieval.rank_tools("opaque multilingual intent", entries, embed_model="test")
            assert result.mode == "hybrid" and not result.degraded
        assert calls == [("alice", "opaque multilingual intent")]
    finally:
        request_embedding_cache.reset(token)
        usage_owner_id.reset(owner_token)
        cache.close()


def test_discovery_reused_in_followup_with_fresh_schema_and_permissions(setup):
    runtime, _ = setup
    add_noise(runtime, 30)
    found = json.loads(discovery.discover_app_tools("play music", session_id="music-regression"))
    assert {SEARCH, PLAY} <= set(found["activated_tool_names"])
    runtime.edge_registry.tools[DEVICE][PLAY]["schema"]["function"]["description"] = "Updated playback interface"
    decision = select(runtime, "再来一次")
    assert {SEARCH, PLAY} <= {e.name for e in decision.selected_edge_tools}
    assert next(e.description for e in decision.selected_edge_tools if e.name == PLAY) == "Updated playback interface"
    assert decision.reused_tool_count >= 2
    decision = select(runtime, "再来一次", disabled={PLAY, SEARCH})
    assert not {PLAY, SEARCH} & {e.name for e in decision.selected_edge_tools}
    # Revocation removes cached names. Re-enabling can independently recall a
    # function through a currently visible dependency, without stale permissions.
    from yumi.core.platform.tools.session_tools import recent_tools

    assert not {PLAY, SEARCH} & set(recent_tools(LOCAL_IDENTITY.user_id, "music-regression", {PLAY, SEARCH}))


def test_small_catalog_recalls_core_timer_without_discovery(setup, monkeypatch):
    runtime, _ = setup
    monkeypatch.setattr(retrieval, "rank_tools", lambda *a, **kw: pytest.fail("no remote retrieval needed"))
    decision = select(runtime, "set_timer")
    assert "set_timer" in {t["function"]["name"] for t in decision.tools}


def test_reused_tool_schema_order_is_stable_across_followups(setup):
    runtime, _ = setup
    add_noise(runtime, 30)
    discovery.discover_app_tools("play music", session_id="music-regression")
    assert select(runtime, "再来一次").tools == select(runtime, "继续吧").tools


def test_search_alone_keeps_playback_dependency(setup):
    entries = discovery._catalog()
    search = next(e for e in entries if e.name == SEARCH)
    assert {SEARCH, PLAY} <= {e.name for e in retrieval.with_companions([search], entries)}


def test_created_reminder_keeps_update_for_implicit_time_correction(setup):
    from yumi.core.platform.tools.session_tools import remember_tools

    runtime, _ = setup
    add_noise(runtime, 30)
    create, update = "edge_tasks__create_seed", "edge_tasks__update_seed"
    runtime.edge_registry.tools["tasks"] = {
        create: {"schema": schema(create, "Create a reminder")},
        update: {"schema": schema(update, "Modify an existing reminder")},
    }
    remember_tools(LOCAL_IDENTITY.user_id, "music-regression", [create])
    decision = select(runtime, "Oh sorry, it should be 3 pm")
    assert update in {e.name for e in decision.selected_edge_tools}
    assert update not in {
        e.name for e in select(runtime, "Oh sorry, it should be 3 pm", disabled={update}).selected_edge_tools
    }


@pytest.mark.parametrize("noise", [0, 300])
def test_current_room_edge_name_and_shared_description_keep_music_chain(setup, noise):
    runtime, cfg = setup
    new_device = "RoomLightsMusicMacMini"
    purpose = (
        "Room Lights and Music on the user's Mac mini controls the bedside and ceiling "
        "lights in their room and plays Apple Music with optional audio-reactive lighting. "
    )
    current = {}
    for name, raw in runtime.edge_registry.tools.pop(DEVICE).items():
        new_name = name.replace(DEVICE, new_device)
        raw["schema"]["function"]["name"] = new_name
        raw["schema"]["function"]["description"] = purpose + raw["schema"]["function"]["description"]
        current[new_name] = raw
    runtime.edge_registry.tools[new_device] = current
    add_noise(runtime, noise)
    decision = select(runtime, "我想听 aimyon 的 naked heart")
    assert {SEARCH.replace(DEVICE, new_device), PLAY.replace(DEVICE, new_device)} <= {
        e.name for e in decision.selected_edge_tools
    }
    assert token_estimate(decision.tools) <= cfg.tool_schema_token_budget
