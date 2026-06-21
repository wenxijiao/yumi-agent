"""Server bind address resolves to loopback by default (LAN is opt-in)."""

import yumi.core.api.app_factory as app_factory


def test_defaults_to_loopback(monkeypatch):
    monkeypatch.delenv("YUMI_HOST", raising=False)
    monkeypatch.delenv("YUMI_PORT", raising=False)
    assert app_factory._server_host_port() == ("127.0.0.1", 8000)


def test_env_overrides_host_and_port(monkeypatch):
    monkeypatch.setenv("YUMI_HOST", "0.0.0.0")
    monkeypatch.setenv("YUMI_PORT", "9000")
    assert app_factory._server_host_port() == ("0.0.0.0", 9000)


def test_blank_host_falls_back_to_loopback(monkeypatch):
    monkeypatch.setenv("YUMI_HOST", "   ")
    monkeypatch.delenv("YUMI_PORT", raising=False)
    assert app_factory._server_host_port() == ("127.0.0.1", 8000)


def test_bad_port_falls_back(monkeypatch):
    monkeypatch.setenv("YUMI_HOST", "0.0.0.0")
    monkeypatch.setenv("YUMI_PORT", "not-a-port")
    assert app_factory._server_host_port() == ("0.0.0.0", 8000)
