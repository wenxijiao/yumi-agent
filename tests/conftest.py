"""Shared pytest configuration for OSS tests (single-user)."""

import pytest


@pytest.fixture(autouse=True)
def _isolate_kumi_env(monkeypatch):
    """Strip enterprise-only env vars so tests run cleanly against OSS defaults."""
    for var in (
        "KUMI_TENANCY_MODE",
        "KUMI_DB_URL",
        "KUMI_RELAY_URL",
        "KUMI_ACCESS_TOKEN",
        "KUMI_USER_ACCESS_TOKEN",
    ):
        monkeypatch.delenv(var, raising=False)
