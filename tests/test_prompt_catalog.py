"""Tests for the versioned, centralized chat prompt catalog."""

from yumi.core.features.prompts.catalog import (
    CHAT_PROMPT_CATALOG_HASH,
    CHAT_PROMPT_VERSION,
    DEFAULT_SYSTEM_PROMPT,
    prompt_catalog_metadata,
)
from yumi.core.features.prompts.defaults import DEFAULT_SYSTEM_PROMPT as LEGACY_DEFAULT_SYSTEM_PROMPT


def test_catalog_exposes_version_and_content_hash() -> None:
    metadata = prompt_catalog_metadata()

    assert metadata == {
        "prompt_version": CHAT_PROMPT_VERSION,
        "prompt_catalog_hash": CHAT_PROMPT_CATALOG_HASH,
    }
    assert CHAT_PROMPT_VERSION == "1.2.1"
    assert len(CHAT_PROMPT_CATALOG_HASH) == 16
    int(CHAT_PROMPT_CATALOG_HASH, 16)


def test_legacy_defaults_import_uses_catalog_source() -> None:
    assert LEGACY_DEFAULT_SYSTEM_PROMPT is DEFAULT_SYSTEM_PROMPT


def test_default_prompt_distinguishes_parallel_and_sequential_tool_calls() -> None:
    assert "execute those calls in parallel" in DEFAULT_SYSTEM_PROMPT
    assert "Call tools sequentially when a later call depends on an earlier result" in DEFAULT_SYSTEM_PROMPT
