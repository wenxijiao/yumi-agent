"""Shared pytest configuration for OSS tests (single-user)."""

import pytest


@pytest.fixture(autouse=True)
def _isolate_yumi_env(monkeypatch):
    """Strip enterprise-only env vars so tests run cleanly against OSS defaults."""
    for var in (
        "YUMI_TENANCY_MODE",
        "YUMI_DB_URL",
        "YUMI_RELAY_URL",
        "YUMI_ACCESS_TOKEN",
        "YUMI_USER_ACCESS_TOKEN",
    ):
        monkeypatch.delenv(var, raising=False)
