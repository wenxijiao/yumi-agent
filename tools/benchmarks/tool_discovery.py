"""Offline routing latency/recall benchmark; no live provider or device calls.

Run: .venv/bin/python -m tools.benchmarks.tool_discovery
Numbers cover routing only, not LLM generation, memory recall or device execution.
"""

import json
import statistics
import time
from pathlib import Path
from unittest.mock import patch

from yumi.core.features.config import ModelConfig
from yumi.core.platform.plugins import LOCAL_IDENTITY
from yumi.core.platform.tools import retrieval, routing, tool
from yumi.tools.bootstrap import init_yumi


def schema(name, description, params=None):
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


def main():
    specs = json.loads((Path(__file__).resolve().parents[2] / "tests/fixtures/room_music_tools.json").read_text())
    device = "RoomMusicMacMini"
    room = {
        f"edge_{device}__{s['name']}": {"schema": schema(f"edge_{device}__{s['name']}", s["description"], s["params"])}
        for s in specs
    }
    required = {f"edge_{device}__music_search", f"edge_{device}__music_play"}
    cfg = ModelConfig(edge_tools_routing_mode="on_demand", embedding_model=None)
    core = {}
    with (
        patch.object(tool, "TOOL_REGISTRY", core),
        patch.object(routing, "TOOL_REGISTRY", core),
        patch.object(routing, "load_model_config", lambda: cfg),
    ):
        init_yumi()
        for count, kind in [
            (0, "disabled"),
            (300, "disabled"),
            (1000, "disabled"),
            (300, "cold"),
            (300, "warm"),
            (300, "slow"),
        ]:
            cfg.embedding_model = None if kind == "disabled" else "offline-simulation"
            calls = []

            def embed(model, text, **kw):
                if kw.get("persistent"):
                    if kind == "cold":
                        return None
                    return [1.0, 0.0] if device in text else [0.0, 1.0]
                calls.append(text)
                if kind == "slow":
                    time.sleep(1.2)
                return [1.0, 0.0]

            registry = {
                device: room,
                "factory": {
                    f"edge_factory__machine_{i}": {
                        "schema": schema(f"edge_factory__machine_{i}", "Calibrate industrial pressure sensors. " * 8)
                    }
                    for i in range(count)
                },
            }
            durations = []
            with patch.object(retrieval, "_cached_embedding", embed):
                for _ in range(1 if kind == "slow" else 10):
                    started = time.perf_counter()
                    result = routing.select_tool_schemas(
                        identity=LOCAL_IDENTITY,
                        query="我想听 aimyon 的 naked heart",
                        session_id="offline-benchmark",
                        disabled_tools=set(),
                        edge_registry=registry,
                    )
                    durations.append((time.perf_counter() - started) * 1000)
                    assert required <= {e.name for e in result.selected_edge_tools}
            print(
                json.dumps(
                    {
                        "edge_tools": count + len(room),
                        "semantic": kind,
                        "median_ms": round(statistics.median(durations), 2),
                        "max_ms": round(max(durations), 2),
                        "mode": result.retrieval_mode,
                        "degraded_reason": result.retrieval_degraded_reason,
                        "query_calls": len(calls),
                        "music_chain_recall": "2/2",
                    }
                )
            )


if __name__ == "__main__":
    main()
