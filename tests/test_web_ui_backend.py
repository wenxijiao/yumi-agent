"""Backend additions for the rebuilt web UI: token usage, /stats, /tts."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from yumi.core.api import app
from yumi.core.platform.http.schemas import TtsRequest
from yumi.core.platform.plugins import LOCAL_IDENTITY
from yumi.core.platform.storage.sqlite_store import SQLiteStore

# ── token_usage store layer ──────────────────────────────────────────────


def _store(tmp_path: Path) -> SQLiteStore:
    return SQLiteStore(tmp_path / "yumi.db")


def test_record_and_summarize_token_usage(tmp_path):
    store = _store(tmp_path)
    store.record_token_usage(session_id="s1", model="gpt-4o", prompt_tokens=100, completion_tokens=40)
    store.record_token_usage(session_id="s1", model="gpt-4o", prompt_tokens=50, completion_tokens=10)
    store.record_token_usage(session_id="s2", model="claude-3", prompt_tokens=20, completion_tokens=5)

    summary = store.token_usage_summary()
    assert summary["turns"] == 3
    assert summary["total_tokens"] == 225
    assert summary["prompt_tokens"] == 170
    assert summary["completion_tokens"] == 55
    models = {m["model"]: m for m in summary["by_model"]}
    assert models["gpt-4o"]["total_tokens"] == 200
    assert models["claude-3"]["total_tokens"] == 25
    # by_model is ordered by total_tokens desc
    assert summary["by_model"][0]["model"] == "gpt-4o"


def test_token_usage_summary_scoped_to_session(tmp_path):
    store = _store(tmp_path)
    store.record_token_usage(session_id="s1", model="m", prompt_tokens=100, completion_tokens=0)
    store.record_token_usage(session_id="s2", model="m", prompt_tokens=999, completion_tokens=0)
    assert store.token_usage_summary(session_id="s1")["total_tokens"] == 100


def test_token_usage_blank_model_becomes_unknown(tmp_path):
    store = _store(tmp_path)
    store.record_token_usage(session_id="s1", model="", prompt_tokens=10, completion_tokens=2)
    assert store.token_usage_summary()["by_model"][0]["model"] == "unknown"


def test_token_usage_timeseries_returns_today(tmp_path):
    store = _store(tmp_path)
    store.record_token_usage(session_id="s1", model="m", prompt_tokens=7, completion_tokens=3)
    series = store.token_usage_timeseries(days=7)
    assert len(series) == 1
    assert series[0]["total_tokens"] == 10
    assert "day" in series[0]


# ── UsageRecorder persistence hook ───────────────────────────────────────


def test_usage_recorder_persists_to_store(tmp_path, monkeypatch):
    from yumi.core.platform.dispatch import usage as usage_mod

    store = _store(tmp_path)
    monkeypatch.setattr(
        "yumi.core.features.memory.store.get_memory_store",
        lambda: SimpleNamespace(sqlite=store),
    )

    ctx = SimpleNamespace(session_id="sess-xyz")
    with usage_mod.UsageRecorder(ctx, bot=None, owner_uid="owner") as rec:
        rec.add({"prompt_tokens": 30, "completion_tokens": 12, "model": "test-model"})

    summary = store.token_usage_summary()
    assert summary["turns"] == 1
    assert summary["total_tokens"] == 42
    assert summary["by_model"][0]["model"] == "test-model"


def test_usage_recorder_skips_zero_tokens(tmp_path, monkeypatch):
    from yumi.core.platform.dispatch import usage as usage_mod

    store = _store(tmp_path)
    monkeypatch.setattr(
        "yumi.core.features.memory.store.get_memory_store",
        lambda: SimpleNamespace(sqlite=store),
    )
    ctx = SimpleNamespace(session_id="sess-empty")
    with usage_mod.UsageRecorder(ctx, bot=None, owner_uid="owner"):
        pass
    assert store.token_usage_summary()["turns"] == 0


# ── /stats endpoint ──────────────────────────────────────────────────────


def test_stats_endpoint_shape():
    client = TestClient(app)
    r = client.get("/stats")
    assert r.status_code == 200
    data = r.json()
    for key in ("generated_at", "tools", "sessions", "tool_calls", "tokens"):
        assert key in data
    assert "total" in data["tools"]


# ── /tts/synthesize endpoint ─────────────────────────────────────────────


def test_tts_endpoint_rejects_empty_text():
    from yumi.core.features.tts.router import tts_synthesize_endpoint

    with pytest.raises(HTTPException) as ei:
        asyncio.run(tts_synthesize_endpoint(LOCAL_IDENTITY, TtsRequest(text="   ")))
    assert ei.value.status_code == 422


def test_tts_endpoint_reports_not_configured(monkeypatch):
    from yumi.core.features.tts.base import TtsNotConfiguredError
    from yumi.core.features.tts.router import tts_synthesize_endpoint

    def _raise(*_a, **_k):
        raise TtsNotConfiguredError("TTS is not enabled")

    monkeypatch.setattr("yumi.core.features.tts.create_tts_provider", _raise)
    with pytest.raises(HTTPException) as ei:
        asyncio.run(tts_synthesize_endpoint(LOCAL_IDENTITY, TtsRequest(text="hello")))
    assert ei.value.status_code == 400


def test_tts_endpoint_returns_audio(monkeypatch):
    from yumi.core.features.tts.router import tts_synthesize_endpoint
    from yumi.core.features.tts.types import SpeechAudio

    class _FakeProvider:
        async def synthesize(self, text, *, voice=None, language=None):
            assert text == "hello world"
            return SpeechAudio(data=b"RIFFfake", format="wav", sample_rate=22050, voice=voice)

    monkeypatch.setattr("yumi.core.features.tts.create_tts_provider", lambda: _FakeProvider())
    resp = asyncio.run(tts_synthesize_endpoint(LOCAL_IDENTITY, TtsRequest(text="hello world")))
    assert resp.media_type == "audio/wav"
    assert resp.body == b"RIFFfake"
