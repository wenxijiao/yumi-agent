"""Server bind address resolves to loopback by default (LAN is opt-in)."""

from pathlib import Path

import yumi.core.api
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


def test_run_app_from_env_binds_loopback_by_default(monkeypatch):
    monkeypatch.delenv("YUMI_HOST", raising=False)
    monkeypatch.delenv("YUMI_PORT", raising=False)
    captured: dict = {}
    monkeypatch.setattr(app_factory.uvicorn, "run", lambda _app, **kw: captured.update(kw))
    app_factory.run_app_from_env()
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8000


def test_package_main_delegates_with_no_hardcoded_host():
    # The real `python -m yumi.core.api` entry point must go through
    # run_app_from_env (loopback default), not hardcode the host.
    main_src = (Path(yumi.core.api.__file__).parent / "__main__.py").read_text(encoding="utf-8")
    assert "run_app_from_env" in main_src
    assert "0.0.0.0" not in main_src
