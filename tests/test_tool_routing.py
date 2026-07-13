from __future__ import annotations

import pytest
from yumi.core.features.config import ModelConfig
from yumi.core.platform.plugins import LOCAL_IDENTITY
from yumi.core.platform.tools.routing import (
    clear_tool_routing_traces,
    list_tool_routing_traces,
    record_tool_routing_usage,
    select_tool_schemas,
)
from yumi.core.platform.tools.tool import TOOL_REGISTRY


def _schema(name: str, description: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {
                    "value": {"type": "string", "description": f"Value for {description}"},
                },
                "required": ["value"],
            },
        },
    }


def _edge_registry(count: int, *, special_name: str = "edge_lab__set_kitchen_lights") -> dict:
    tools = {}
    for i in range(count):
        name = f"edge_lab__generic_tool_{i}"
        desc = f"Generic factory operation number {i}"
        tools[name] = {"schema": _schema(name, desc)}
    tools[special_name] = {
        "schema": _schema(
            special_name,
            "Turn on, turn off, dim, or brighten the kitchen lights in the lab.",
        )
    }
    return {"lab": tools}


@pytest.fixture(autouse=True)
def _restore_tool_registry(monkeypatch):
    original = dict(TOOL_REGISTRY)
    TOOL_REGISTRY.clear()
    TOOL_REGISTRY.update(
        {
            "remember_user_preference": {
                "schema": _schema("remember_user_preference", "Store an important user memory."),
                "callable": lambda value: value,
            },
            "read_file": {
                "schema": _schema("read_file", "Read a local file for context."),
                "callable": lambda value: value,
            },
        }
    )
    monkeypatch.setattr(
        "yumi.core.platform.tools.routing.load_model_config",
        # always_expose_below=0 keeps these tests exercising the ranking/limit path;
        # the small-edge always-expose guarantee is covered by its own tests below.
        # routing_mode is pinned to the legacy per-turn ranking these tests were
        # written for; sticky-mode behavior has its own test group below.
        lambda: ModelConfig(
            edge_tools_enable_dynamic_routing=True,
            edge_tools_routing_mode="per_turn",
            edge_tools_retrieval_limit=3,
            edge_tools_always_expose_below=0,
        ),
    )
    clear_tool_routing_traces()
    yield
    TOOL_REGISTRY.clear()
    TOOL_REGISTRY.update(original)
    clear_tool_routing_traces()


def test_core_tools_are_always_loaded_and_edge_tools_are_ranked():
    decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="Please turn on the kitchen lights",
        session_id="s1",
        disabled_tools=set(),
        edge_registry=_edge_registry(25),
    )

    names = [tool["function"]["name"] for tool in decision.tools]
    assert "remember_user_preference" in names
    assert "read_file" in names
    assert "edge_lab__set_kitchen_lights" in names
    assert len(decision.selected_edge_tools) == 3
    assert decision.total_edge_tools == 26


def test_forced_edge_tool_does_not_consume_retrieval_limit():
    decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="Do a generic factory operation",
        session_id="s1",
        disabled_tools=set(),
        edge_registry=_edge_registry(50),
        force_edge_tool_names={"edge_lab__set_kitchen_lights"},
    )

    selected = [entry.name for entry in decision.selected_edge_tools]
    assert "edge_lab__set_kitchen_lights" in selected
    assert len(selected) == 4

    trace = list_tool_routing_traces(session_id="s1", limit=1)[0]
    assert trace["forced_edge_count"] == 1
    assert trace["retrieved_edge_count"] == 3


def test_queries_match_edge_descriptions_or_lexical():
    registry = _edge_registry(20, special_name="edge_home__open_curtain")
    registry["lab"]["edge_home__open_curtain"] = {
        "schema": _schema("edge_home__open_curtain", "Open the living room curtains and adjust shade level.")
    }

    decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="open the living room curtains",
        session_id="s1",
        disabled_tools=set(),
        edge_registry=registry,
    )

    selected = [entry.name for entry in decision.selected_edge_tools]
    assert "edge_home__open_curtain" in selected


def test_concurrent_routing_choices_match_distinct_edge_descriptions():
    registry = _edge_registry(20, special_name="edge_home__open_blinds")
    registry["lab"]["edge_home__open_blinds"] = {
        "schema": _schema("edge_home__open_blinds", "Open the living room blinds and adjust ambient light.")
    }
    registry["lab"]["edge_home__start_bath"] = {
        "schema": _schema("edge_home__start_bath", "Start the bath heater and set the target water temperature.")
    }

    first_decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="open the living room blinds",
        session_id="s1",
        disabled_tools=set(),
        edge_registry=registry,
    )
    second_decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="start heating the bath water",
        session_id="s1",
        disabled_tools=set(),
        edge_registry=registry,
    )

    assert "edge_home__open_blinds" in [entry.name for entry in first_decision.selected_edge_tools]
    assert "edge_home__start_bath" in [entry.name for entry in second_decision.selected_edge_tools]


def test_embedding_routing_is_preferred_over_lexical_matching(monkeypatch):
    class FakeEmbedProvider:
        def embed(self, model: str, text: str) -> list[float]:  # noqa: ARG002
            if text == "semantic request target" or "opaque device alpha" in text:
                return [1.0, 0.0]
            return [0.0, 1.0]

    monkeypatch.setattr(
        "yumi.core.platform.tools.routing.load_model_config",
        lambda: ModelConfig(
            embedding_model="fake-embedding",
            edge_tools_enable_dynamic_routing=True,
            edge_tools_retrieval_limit=1,
            edge_tools_always_expose_below=0,
        ),
    )
    monkeypatch.setattr("yumi.core.platform.tools.routing.get_embed_provider", lambda: FakeEmbedProvider())
    registry = {
        "lab": {
            "edge_lab__generic_match": {"schema": _schema("edge_lab__generic_match", "semantic request target")},
            "edge_lab__embedding_only": {"schema": _schema("edge_lab__embedding_only", "opaque device alpha")},
        }
    }

    decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="semantic request target",
        session_id="s1",
        disabled_tools=set(),
        edge_registry=registry,
    )

    assert [entry.name for entry in decision.selected_edge_tools] == ["edge_lab__embedding_only"]


def test_meaningful_edge_name_prioritizes_tools_on_that_edge():
    registry = {
        "bedroom": {
            "edge_bedroom__set_light": {
                "schema": _schema("edge_bedroom__set_light", "Set the brightness and power state for a light.")
            }
        },
        "kitchen": {
            "edge_kitchen__set_light": {
                "schema": _schema("edge_kitchen__set_light", "Set the brightness and power state for a light.")
            }
        },
    }

    decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="turn on the bedroom light",
        session_id="s1",
        disabled_tools=set(),
        edge_registry=registry,
    )

    assert [entry.name for entry in decision.selected_edge_tools[:1]] == ["edge_bedroom__set_light"]


def test_tool_description_still_works_when_edge_name_is_not_meaningful():
    registry = {
        "device-001": {
            "edge_device__make_coffee": {
                "schema": _schema("edge_device__make_coffee", "Start brewing coffee and choose cup size.")
            }
        },
        "device-002": {
            "edge_device__set_fan": {"schema": _schema("edge_device__set_fan", "Set fan speed and oscillation.")}
        },
    }

    decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="brew coffee",
        session_id="s1",
        disabled_tools=set(),
        edge_registry=registry,
    )

    assert [entry.name for entry in decision.selected_edge_tools[:1]] == ["edge_device__make_coffee"]


def test_disabled_tools_are_not_loaded():
    decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="remember this and turn on kitchen lights",
        session_id="s1",
        disabled_tools={"remember_user_preference", "edge_lab__set_kitchen_lights"},
        edge_registry=_edge_registry(10),
    )

    names = [tool["function"]["name"] for tool in decision.tools]
    assert "remember_user_preference" not in names
    assert "edge_lab__set_kitchen_lights" not in names
    assert "read_file" in names


def test_dynamic_routing_can_be_disabled(monkeypatch):
    monkeypatch.setattr(
        "yumi.core.platform.tools.routing.load_model_config",
        lambda: ModelConfig(
            edge_tools_enable_dynamic_routing=False,
            edge_tools_retrieval_limit=3,
            edge_tools_always_expose_below=0,
        ),
    )

    decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="kitchen lights",
        session_id="s1",
        disabled_tools=set(),
        edge_registry=_edge_registry(12),
    )

    assert len(decision.selected_edge_tools) == 13


def test_zero_edge_limit_hides_unforced_edge_tools(monkeypatch):
    monkeypatch.setattr(
        "yumi.core.platform.tools.routing.load_model_config",
        lambda: ModelConfig(
            edge_tools_enable_dynamic_routing=True,
            edge_tools_routing_mode="per_turn",
            edge_tools_retrieval_limit=0,
            edge_tools_always_expose_below=0,
        ),
    )

    decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="kitchen lights",
        session_id="s1",
        disabled_tools=set(),
        edge_registry=_edge_registry(12),
    )

    assert decision.selected_edge_tools == []
    assert len(decision.tools) == len(TOOL_REGISTRY)


def test_always_include_edge_tool_bypasses_dynamic_routing_limit(monkeypatch):
    monkeypatch.setattr(
        "yumi.core.platform.tools.routing.load_model_config",
        lambda: ModelConfig(
            edge_tools_enable_dynamic_routing=True,
            edge_tools_retrieval_limit=0,
            edge_tools_always_expose_below=0,
        ),
    )
    registry = _edge_registry(12)
    registry["lab"]["edge_lab__set_kitchen_lights"]["always_include"] = True

    decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="generic factory operation",
        session_id="s1",
        disabled_tools=set(),
        edge_registry=registry,
    )

    selected = [entry.name for entry in decision.selected_edge_tools]
    assert selected == ["edge_lab__set_kitchen_lights"]
    assert "edge_lab__set_kitchen_lights" in [tool["function"]["name"] for tool in decision.tools]


def test_always_include_edge_tool_does_not_consume_retrieval_limit(monkeypatch):
    monkeypatch.setattr(
        "yumi.core.platform.tools.routing.load_model_config",
        lambda: ModelConfig(
            edge_tools_enable_dynamic_routing=True,
            edge_tools_routing_mode="per_turn",
            edge_tools_retrieval_limit=1,
            edge_tools_always_expose_below=0,
        ),
    )
    registry = _edge_registry(12)
    registry["lab"]["edge_lab__set_kitchen_lights"]["always_include"] = True

    decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="generic factory operation",
        session_id="s1",
        disabled_tools=set(),
        edge_registry=registry,
    )

    selected = [entry.name for entry in decision.selected_edge_tools]
    assert "edge_lab__set_kitchen_lights" in selected
    assert len(selected) == 2

    trace = list_tool_routing_traces(session_id="s1", limit=1)[0]
    assert trace["pinned_edge_count"] == 1
    assert trace["retrieved_edge_count"] == 1


def test_mentioned_edge_device_tools_do_not_consume_retrieval_limit(monkeypatch):
    monkeypatch.setattr(
        "yumi.core.platform.tools.routing.load_model_config",
        lambda: ModelConfig(
            edge_tools_enable_dynamic_routing=True,
            edge_tools_routing_mode="per_turn",
            edge_tools_retrieval_limit=1,
            edge_tools_always_expose_below=0,
        ),
    )
    registry = _edge_registry(12)
    registry["u:u42::my windows"] = {
        "edge_u42__my_windows__ping": {
            "schema": _schema("edge_u42__my_windows__ping", "Print a short message on my Windows desktop.")
        }
    }

    decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="Use my windows to print a test message",
        session_id="s1",
        disabled_tools=set(),
        edge_registry=registry,
    )

    selected = [entry.name for entry in decision.selected_edge_tools]
    assert "edge_u42__my_windows__ping" in selected
    assert len(selected) == 2

    trace = list_tool_routing_traces(session_id="s1", limit=1)[0]
    assert trace["mentioned_edge_count"] == 1
    assert trace["retrieved_edge_count"] == 1


def test_routing_and_usage_telemetry_are_recorded():
    select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="kitchen lights",
        session_id="s1",
        disabled_tools=set(),
        edge_registry=_edge_registry(10),
    )
    record_tool_routing_usage(session_id="s1", prompt_tokens=123, completion_tokens=45, model="test-model")

    traces = list_tool_routing_traces(session_id="s1", limit=10)
    assert any(rec.get("selected_edge_tools") for rec in traces)
    assert any(rec.get("type") == "usage" and rec.get("prompt_tokens") == 123 for rec in traces)


@pytest.mark.parametrize("count", [10, 50, 100, 500, 1000])
def test_edge_tool_routing_scales_to_large_registries(count):
    decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="Adjust the kitchen lights",
        session_id=f"scale-{count}",
        disabled_tools=set(),
        edge_registry=_edge_registry(count),
    )

    selected = [entry.name for entry in decision.selected_edge_tools]
    assert "edge_lab__set_kitchen_lights" in selected
    assert len(selected) <= 3
    assert len(decision.tools) <= len(TOOL_REGISTRY) + 3


def test_small_edge_is_always_exposed_even_when_limit_is_zero(monkeypatch):
    # Blackout-prevention guarantee: a freshly scaffolded edge with a few tools
    # stays fully callable even if an operator sets the retrieval limit to 0.
    monkeypatch.setattr(
        "yumi.core.platform.tools.routing.load_model_config",
        lambda: ModelConfig(
            edge_tools_enable_dynamic_routing=True,
            edge_tools_retrieval_limit=0,
            edge_tools_always_expose_below=10,
        ),
    )
    decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="something totally unrelated to any tool",
        session_id="s1",
        disabled_tools=set(),
        edge_registry=_edge_registry(2),  # 3 edge tools total (<= 10)
    )

    assert len(decision.selected_edge_tools) == 3
    assert "edge_lab__set_kitchen_lights" in [e.name for e in decision.selected_edge_tools]


def test_small_edge_below_threshold_bypasses_ranking(monkeypatch):
    monkeypatch.setattr(
        "yumi.core.platform.tools.routing.load_model_config",
        lambda: ModelConfig(
            edge_tools_enable_dynamic_routing=True,
            edge_tools_retrieval_limit=1,
            edge_tools_always_expose_below=10,
        ),
    )
    decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="an unrelated query",
        session_id="s1",
        disabled_tools=set(),
        edge_registry=_edge_registry(3),  # 4 edge tools total (<= 10)
    )

    assert len(decision.selected_edge_tools) == 4


def test_large_edge_above_threshold_is_still_ranked(monkeypatch):
    monkeypatch.setattr(
        "yumi.core.platform.tools.routing.load_model_config",
        lambda: ModelConfig(
            edge_tools_enable_dynamic_routing=True,
            edge_tools_retrieval_limit=3,
            edge_tools_always_expose_below=10,
        ),
    )
    decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="Adjust the kitchen lights",
        session_id="s1",
        disabled_tools=set(),
        edge_registry=_edge_registry(15),  # 16 edge tools total (> 10): still ranked
    )

    assert len(decision.selected_edge_tools) == 3
    assert "edge_lab__set_kitchen_lights" in [e.name for e in decision.selected_edge_tools]


# ── sticky mode ─────────────────────────────────────────────────────────────
# Sticky routing keeps the tools array stable across turns (provider prompt
# caching) by attaching whole edges per session instead of re-ranking per turn.

from yumi.core.platform.tools import routing as routing_mod
from yumi.core.platform.tools.routing import (
    clear_session_edges,
    note_edge_tool_used,
    search_edge_tools,
)


def _sticky_config(**overrides):
    base = dict(
        edge_tools_enable_dynamic_routing=True,
        edge_tools_routing_mode="sticky",
        edge_tools_retrieval_limit=3,
        edge_tools_always_expose_below=0,
    )
    base.update(overrides)
    return ModelConfig(**base)


def _two_edge_registry() -> dict:
    lab = {f"edge_lab__tool_{i}": {"schema": _schema(f"edge_lab__tool_{i}", f"Lab op {i}")} for i in range(6)}
    kit = {f"edge_kit__tool_{i}": {"schema": _schema(f"edge_kit__tool_{i}", f"Kitchen helper {i}")} for i in range(5)}
    return {"lab": lab, "kit": kit}


def test_sticky_cold_start_falls_back_to_ranking(monkeypatch):
    monkeypatch.setattr("yumi.core.platform.tools.routing.load_model_config", _sticky_config)
    clear_session_edges("ss_cold")
    decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="Please turn on the kitchen lights",
        session_id="ss_cold",
        disabled_tools=set(),
        edge_registry=_edge_registry(25),
    )
    selected = [e.name for e in decision.selected_edge_tools]
    assert len(selected) == 3
    assert "edge_lab__set_kitchen_lights" in selected


def test_sticky_used_edge_stays_attached_and_ordering_is_stable(monkeypatch):
    monkeypatch.setattr("yumi.core.platform.tools.routing.load_model_config", _sticky_config)
    clear_session_edges("ss_used")
    registry = _two_edge_registry()
    note_edge_tool_used("ss_used", "lab")

    first = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="anything unrelated at all",
        session_id="ss_used",
        disabled_tools=set(),
        edge_registry=registry,
    )
    first_names = [e.name for e in first.selected_edge_tools]
    # The WHOLE kit of the used edge is attached (tool chains stay usable) …
    assert set(first_names) == set(registry["lab"].keys())

    second = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="a completely different query wording",
        session_id="ss_used",
        disabled_tools=set(),
        edge_registry=registry,
    )
    # … and the array is IDENTICAL across turns regardless of the query.
    assert [e.name for e in second.selected_edge_tools] == first_names


def test_sticky_lru_edge_is_evicted_over_session_cap(monkeypatch):
    monkeypatch.setattr(
        "yumi.core.platform.tools.routing.load_model_config",
        lambda: _sticky_config(edge_tools_session_max=8),
    )
    clear_session_edges("ss_lru")
    registry = _two_edge_registry()  # lab: 6 tools, kit: 5 tools → 11 > 8
    note_edge_tool_used("ss_lru", "lab")
    note_edge_tool_used("ss_lru", "kit")

    decision = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="whatever",
        session_id="ss_lru",
        disabled_tools=set(),
        edge_registry=registry,
    )
    selected = {e.name for e in decision.selected_edge_tools}
    # lab was used first → least recently used → evicted; kit stays.
    assert selected == set(registry["kit"].keys())
    assert set(routing_mod.active_edge_keys_for_session("ss_lru").keys()) == {"kit"}


def test_sticky_mentioned_device_becomes_sticky(monkeypatch):
    monkeypatch.setattr("yumi.core.platform.tools.routing.load_model_config", _sticky_config)
    clear_session_edges("ss_mention")
    registry = _edge_registry(25)

    select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="use the lab device please",
        session_id="ss_mention",
        disabled_tools=set(),
        edge_registry=registry,
    )
    assert "lab" in routing_mod.active_edge_keys_for_session("ss_mention")

    # A later, unrelated query still exposes the full lab kit.
    later = select_tool_schemas(
        identity=LOCAL_IDENTITY,
        query="tell me a joke",
        session_id="ss_mention",
        disabled_tools=set(),
        edge_registry=registry,
    )
    assert {e.name for e in later.selected_edge_tools} == set(registry["lab"].keys())


def test_search_edge_tools_ranks_by_need(monkeypatch):
    monkeypatch.setattr("yumi.core.platform.tools.routing.load_model_config", _sticky_config)
    matches = search_edge_tools(
        "turn on the kitchen lights",
        identity=LOCAL_IDENTITY,
        disabled_tools=set(),
        edge_registry=_edge_registry(25),
        limit=5,
    )
    assert matches
    assert matches[0]["name"] == "edge_lab__set_kitchen_lights"
    assert matches[0]["edge_key"] == "lab"
