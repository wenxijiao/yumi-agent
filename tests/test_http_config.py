"""CORS configuration helpers for core apps."""

import pytest
from yumi.core.platform.security.http_config import DEFAULT_LOCAL_BROWSER_ORIGINS, get_cors_settings


def test_cors_defaults_are_localhost_only(monkeypatch):
    monkeypatch.delenv("TEST_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("TEST_CORS_ALLOW_CREDENTIALS", raising=False)

    settings = get_cors_settings("TEST_CORS_ORIGINS", "TEST_CORS_ALLOW_CREDENTIALS")

    assert settings["allow_origins"] == list(DEFAULT_LOCAL_BROWSER_ORIGINS)
    assert settings["allow_credentials"] is False


def test_cors_wildcard_with_credentials_raises(monkeypatch):
    monkeypatch.setenv("TEST_CORS_ORIGINS", "*")
    monkeypatch.setenv("TEST_CORS_ALLOW_CREDENTIALS", "true")

    with pytest.raises(ValueError, match="cannot be combined"):
        get_cors_settings("TEST_CORS_ORIGINS", "TEST_CORS_ALLOW_CREDENTIALS")


def test_cors_wildcard_without_credentials_passes(monkeypatch):
    monkeypatch.setenv("TEST_CORS_ORIGINS", "*")
    monkeypatch.delenv("TEST_CORS_ALLOW_CREDENTIALS", raising=False)

    settings = get_cors_settings("TEST_CORS_ORIGINS", "TEST_CORS_ALLOW_CREDENTIALS")

    assert settings["allow_origins"] == ["*"]
    assert settings["allow_credentials"] is False


def test_cors_allows_explicit_origin_list(monkeypatch):
    monkeypatch.setenv("TEST_CORS_ORIGINS", "https://app.example, https://admin.example")
    monkeypatch.setenv("TEST_CORS_ALLOW_CREDENTIALS", "1")

    settings = get_cors_settings("TEST_CORS_ORIGINS", "TEST_CORS_ALLOW_CREDENTIALS")

    assert settings["allow_origins"] == ["https://app.example", "https://admin.example"]
    assert settings["allow_credentials"] is True
