"""Lightweight performance baseline for Kumi's hot paths.

Runs four micro-benchmarks that together exercise the surfaces most affected
by the recent refactors:

1. **App boot** — building the FastAPI app (registers all OSS routers, runs
   plugin discovery, materialises the runtime). Measures wall time only;
   ``lifespan`` is *not* executed because that requires a real model config.

2. **Memory message round-trip** — instantiate ``Memory(storage_dir=tmpdir)``,
   write 1000 messages with the embedding pipeline disabled, then list them
   back. Reports messages/sec for write and total list latency.

3. **ChatEvent serialisation** — round-trip 10 000 ``ChatEvent`` objects
   through ``model_dump_json`` / ``parse_chat_event`` to baseline the cost of
   the new typed protocol vs. plain dicts.

4. **CLI registry construction** — build the default ``CommandRegistry`` and
   walk it; covers Phase #3's per-process startup overhead.

Usage
-----

    .venv/bin/python -m tools.benchmarks.run_benchmarks

Each benchmark prints a one-line summary. Re-run after changes to spot
regressions; we do not commit numbers because they're machine-dependent.
The script intentionally avoids any LLM provider calls so it runs offline.
"""

from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

# Make sure the local ``kumi`` package is importable when run from the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


@contextmanager
def _timed(label: str):
    t0 = time.perf_counter()
    yield
    dt_ms = (time.perf_counter() - t0) * 1000
    print(f"  {label:<40s} {dt_ms:8.2f} ms")


# ── 1. App boot ─────────────────────────────────────────────────────────────


def benchmark_app_boot() -> None:
    print("[1] FastAPI app construction")
    # Force a fresh import so we measure the full build, not a cached module.
    for mod in list(sys.modules):
        if mod.startswith("kumi.core.api"):
            del sys.modules[mod]
    with _timed("import + _build_app()"):
        from kumi.core.api.app_factory import app  # noqa: F401


# ── 2. Memory message round-trip ────────────────────────────────────────────


def benchmark_memory_messages(message_count: int = 1000) -> None:
    print(f"[2] Memory message CRUD (n={message_count})")
    from kumi.core.memories.memory import Memory

    with tempfile.TemporaryDirectory() as td:
        m = Memory(session_id="bench", storage_dir=td, max_recent=50)
        # Disable the embedding pipeline so we benchmark storage cost only;
        # the live system runs vectorisation off-thread.
        m._embedding_available = False

        write_start = time.perf_counter()
        for i in range(message_count):
            m.add_message("user", f"hello world {i}")
        write_dt = time.perf_counter() - write_start
        print(f"  {'write add_message':<40s} {write_dt * 1000:8.2f} ms total ({message_count / write_dt:7.1f} msg/s)")

        with _timed("list_messages(limit=200)"):
            rows = m.list_messages(session_id="bench", limit=200)
        assert len(rows) == 200

        with _timed("search_messages substring fallback"):
            results = m.search_messages("hello world 500", session_id="bench", limit=5)
        assert isinstance(results, list)


# ── 3. Event serialisation ──────────────────────────────────────────────────


def benchmark_chat_events(event_count: int = 10_000) -> None:
    print(f"[3] ChatEvent serialise / parse (n={event_count})")
    from kumi.core.api.events import (
        TextEvent,
        ToolStatusEvent,
        parse_chat_event,
        serialize_chat_event,
    )

    events = []
    for i in range(event_count):
        if i % 5 == 0:
            events.append(ToolStatusEvent(status="success", content=f"tool#{i} done"))
        else:
            events.append(TextEvent(content=f"chunk #{i}"))

    serialise_dt = []
    parse_dt = []
    for event in events:
        t0 = time.perf_counter()
        line = serialize_chat_event(event)
        serialise_dt.append(time.perf_counter() - t0)
        t0 = time.perf_counter()
        parse_chat_event(line)
        parse_dt.append(time.perf_counter() - t0)

    print(f"  {'serialize_chat_event (median)':<40s} {statistics.median(serialise_dt) * 1e6:8.2f} µs/event")
    print(f"  {'parse_chat_event (median)':<40s} {statistics.median(parse_dt) * 1e6:8.2f} µs/event")

    # Compare against the legacy free-form dict path.
    legacy_serialise_dt = []
    legacy_parse_dt = []
    for event in events:
        payload = event.model_dump()
        t0 = time.perf_counter()
        line = json.dumps(payload) + "\n"
        legacy_serialise_dt.append(time.perf_counter() - t0)
        t0 = time.perf_counter()
        json.loads(line)
        legacy_parse_dt.append(time.perf_counter() - t0)
    print(
        f"  {'(reference) json.dumps + json.loads':<40s} "
        f"{statistics.median(legacy_serialise_dt) * 1e6:5.2f} µs / "
        f"{statistics.median(legacy_parse_dt) * 1e6:5.2f} µs"
    )


# ── 4. CLI registry ─────────────────────────────────────────────────────────


def benchmark_cli_registry() -> None:
    print("[4] CLI registry construction")
    from kumi.cli.commands import build_default_registry

    with _timed("build_default_registry()"):
        reg = build_default_registry()
    count = sum(1 for _ in reg)
    print(f"  {'commands registered':<40s} {count:8d}")


# ── runner ─────────────────────────────────────────────────────────────────


def main() -> int:
    print("Kumi performance baseline")
    print("=" * 60)
    benchmark_app_boot()
    print()
    benchmark_memory_messages()
    print()
    benchmark_chat_events()
    print()
    benchmark_cli_registry()
    print()
    print("Done. Re-run after changes to spot regressions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
