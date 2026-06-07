"""Contract tests for ``/config/model`` (structured errors and response shape)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from kumi.core.features.config.router import _model_config_public_dict, update_model_config_endpoint
from kumi.core.platform.http.schemas import ModelConfigUpdateRequest


def _patch_config_path(monkeypatch, tmp_path: Path, name: str = "c.json") -> Path:
    p = tmp_path / name
    monkeypatch.setattr("kumi.core.features.config.paths.CONFIG_PATH", p)
    monkeypatch.setattr("kumi.core.features.config.store.CONFIG_PATH", p)
    monkeypatch.setattr("kumi.core.features.config.router.CONFIG_PATH", p)
    return p


def test_put_config_model_rejects_unknown_chat_provider(monkeypatch, tmp_path: Path) -> None:
    p = _patch_config_path(monkeypatch, tmp_path)
    p.write_text(
        json.dumps(
            {
                "chat_provider": "ollama",
                "chat_model": "m",
                "embedding_provider": "ollama",
                "embedding_model": "m",
            }
        ),
        encoding="utf-8",
    )

    async def _run():
        with pytest.raises(HTTPException) as ei:
            await update_model_config_endpoint(ModelConfigUpdateRequest(chat_provider="bogus"))
        return ei.value

    exc = asyncio.run(_run())
    assert exc.status_code == 400
    assert isinstance(exc.detail, dict)
    assert exc.detail["code"] == "KUMI_UNKNOWN_PROVIDER"


def test_put_config_model_missing_openai_key(monkeypatch, tmp_path: Path) -> None:
    p = _patch_config_path(monkeypatch, tmp_path)
    cfg = {
        "chat_provider": "openai",
        "chat_model": "gpt-4o",
        "embedding_provider": "openai",
        "embedding_model": "text-embedding-3-small",
    }
    p.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    import kumi.core.api.state as api_state

    monkeypatch.setattr(api_state, "bot", None)

    async def _run():
        with pytest.raises(HTTPException) as ei:
            await update_model_config_endpoint(ModelConfigUpdateRequest(chat_model="gpt-4o"))
        return ei.value

    exc = asyncio.run(_run())
    assert exc.status_code == 400
    assert exc.detail["code"] == "KUMI_MISSING_OPENAI_KEY"
    restored = json.loads(p.read_text(encoding="utf-8"))
    assert restored["chat_provider"] == cfg["chat_provider"]
    assert restored["chat_model"] == cfg["chat_model"]
    assert restored["embedding_provider"] == cfg["embedding_provider"]
    assert restored["embedding_model"] == cfg["embedding_model"]


def test_model_config_public_dict_includes_key_flags(monkeypatch, tmp_path: Path) -> None:
    p = _patch_config_path(monkeypatch, tmp_path)
    p.write_text(
        json.dumps(
            {
                "chat_provider": "ollama",
                "chat_model": "m",
                "embedding_provider": "ollama",
                "embedding_model": "m",
                "openai_api_key": "sk-test",
            }
        ),
        encoding="utf-8",
    )
    d = _model_config_public_dict()
    assert d["openai_api_key_saved"] is True
    assert "openai_api_key_effective" in d
    assert "gemini_api_key_effective" in d
    assert "deepseek_api_key_saved" in d
    assert "deepseek_api_key_effective" in d
    assert "openai_base_url" in d
    assert "deepseek_base_url" in d
    assert d["edge_tools_enable_dynamic_routing"] is True
    assert d["edge_tools_retrieval_limit"] == 20
    assert d["stt_provider"] == "disabled"
    assert d["stt_backend"] == "faster-whisper"
    assert d["stt_model"] == ""


def test_create_provider_deepseek_wraps_openai_provider():
    pytest.importorskip("openai")
    from kumi.core.platform.providers import create_provider
    from kumi.core.platform.providers.openai_provider import OpenAIProvider

    p = create_provider(
        "deepseek",
        credentials={
            "openai_api_key": None,
            "openai_base_url": None,
            "gemini_api_key": None,
            "claude_api_key": None,
            "deepseek_api_key": "sk-test-deepseek",
            "deepseek_base_url": None,
        },
    )
    assert isinstance(p, OpenAIProvider)


def test_put_config_model_rejects_deepseek_embedding_provider(monkeypatch, tmp_path: Path) -> None:
    p = _patch_config_path(monkeypatch, tmp_path)
    p.write_text(
        json.dumps(
            {
                "chat_provider": "ollama",
                "chat_model": "m",
                "embedding_provider": "ollama",
                "embedding_model": "m",
            }
        ),
        encoding="utf-8",
    )

    async def _run():
        with pytest.raises(HTTPException) as ei:
            await update_model_config_endpoint(ModelConfigUpdateRequest(embedding_provider="deepseek"))
        return ei.value

    exc = asyncio.run(_run())
    assert exc.status_code == 400
    assert "deepseek" in str(exc.detail).lower()


def test_put_config_model_updates_edge_tool_routing_settings(monkeypatch, tmp_path: Path) -> None:
    p = _patch_config_path(monkeypatch, tmp_path)
    p.write_text(
        json.dumps(
            {
                "chat_provider": "ollama",
                "chat_model": "m",
                "embedding_provider": "ollama",
                "embedding_model": "m",
            }
        ),
        encoding="utf-8",
    )

    import kumi.core.api.state as api_state

    monkeypatch.setattr(api_state, "bot", None)
    monkeypatch.setattr("kumi.core.features.config.router.ensure_provider_available", lambda provider: None)

    async def _run():
        return await update_model_config_endpoint(
            ModelConfigUpdateRequest(
                edge_tools_enable_dynamic_routing=False,
                edge_tools_retrieval_limit=7,
            )
        )

    response = asyncio.run(_run())
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert response["edge_tools_enable_dynamic_routing"] is False
    assert response["edge_tools_retrieval_limit"] == 7
    assert saved["edge_tools_enable_dynamic_routing"] is False
    assert saved["edge_tools_retrieval_limit"] == 7
