"""CLI environment selection tests without launching subprocesses."""

import json
import sys
from types import SimpleNamespace

import pytest
import yumi.cli as cli
import yumi.cli.runners as cli_runners
from yumi.core.features.config import setup_wizard


class _TtyStub:
    def isatty(self):
        return True

    def write(self, _text):
        return None

    def flush(self):
        return None


def test_prepare_client_environment_prefers_reachable_direct_server(monkeypatch):
    monkeypatch.setenv("YUMI_SERVER_URL", "http://127.0.0.1:8000")
    monkeypatch.setattr(cli_runners, "is_server_running", lambda url: True)

    env = cli.prepare_client_environment("chat")

    assert env["YUMI_SERVER_URL"] == "http://127.0.0.1:8000"


def test_run_ui_opens_browser_when_server_up(monkeypatch):
    import webbrowser

    opened: list[str] = []
    monkeypatch.setattr(
        cli_runners, "prepare_client_environment", lambda _role: {"YUMI_SERVER_URL": "http://127.0.0.1:8000"}
    )
    monkeypatch.setattr(cli_runners, "is_server_running", lambda url: True)
    monkeypatch.setattr(cli_runners, "_get_lan_ip", lambda: None)
    monkeypatch.setattr(cli_runners, "_print_banner", lambda *args, **kwargs: None)
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url) or True)

    cli_runners.run_ui()

    assert opened == ["http://127.0.0.1:8000/app/"]


def test_run_ui_exits_when_server_down(monkeypatch):
    monkeypatch.setattr(
        cli_runners, "prepare_client_environment", lambda _role: {"YUMI_SERVER_URL": "http://127.0.0.1:8000"}
    )
    monkeypatch.setattr(cli_runners, "is_server_running", lambda url: False)

    with pytest.raises(SystemExit):
        cli_runners.run_ui()


def test_main_dispatches_cleanup_memory(monkeypatch):
    called = {"memory": False}

    monkeypatch.setattr(sys, "argv", ["yumi", "--cleanup-memory"])
    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    monkeypatch.setattr(cli, "run_cleanup_memory", lambda: called.__setitem__("memory", True))

    cli.main()

    assert called["memory"] is True


def test_main_dispatches_cleanup_models(monkeypatch):
    called = {}

    monkeypatch.setattr(sys, "argv", ["yumi", "--cleanup-models", "--include-ollama"])
    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    monkeypatch.setattr(cli, "run_cleanup_models", lambda **kwargs: called.update(kwargs))

    cli.main()

    assert called == {"include_ollama": True}


def test_include_ollama_requires_cleanup_models(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["yumi", "--include-ollama"])
    monkeypatch.setattr(cli, "configure_logging", lambda: None)

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert "Use --include-ollama with --cleanup-models." in str(exc.value)


def test_configured_ollama_models_are_deduplicated(monkeypatch):
    cfg = SimpleNamespace(
        chat_provider="ollama",
        chat_model="qwen3.5:9b",
        embedding_provider="ollama",
        embedding_model="qwen3.5:9b",
    )
    monkeypatch.setattr(cli_runners, "load_saved_model_config", lambda: cfg)

    assert cli_runners._configured_ollama_models() == ["qwen3.5:9b"]


@pytest.mark.parametrize("flag", ["--version", "-v"])
def test_main_prints_version(monkeypatch, capsys, flag):
    monkeypatch.setattr(sys, "argv", ["yumi", flag])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert f"yumi {cli._package_version()}" in out


def test_main_help_is_grouped_and_user_facing(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["yumi", "--help"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "+-" in out
    assert "| Command" in out
    assert "| Quick Start" in out
    assert "| Run Locally" in out
    assert "| Connect Your App" in out
    assert "| Setup And Maintenance" in out
    assert "| Messaging And Voice" in out
    assert "yumi --run-edge" in out
    assert "yumi --cleanup-models" in out
    assert "yumi --server --telegram --discord --line" in out
    assert "terminal chat" in out
    assert "Web UI" in out
    assert "enterprise" not in out.lower()
    assert "commercial" not in out.lower()


def test_setup_messaging_tokens_renders_step5_menu(monkeypatch):
    captured = []

    def fake_select_option(**kwargs):
        captured.append(kwargs)
        return "skip"

    monkeypatch.setattr(cli_runners.sys, "stdin", _TtyStub())
    monkeypatch.setattr(cli_runners.sys, "stdout", _TtyStub())
    monkeypatch.setattr(setup_wizard, "_select_option", fake_select_option)
    monkeypatch.setattr(cli_runners, "get_telegram_bot_token", lambda: "telegram-token")
    monkeypatch.setattr(cli_runners, "get_discord_bot_token", lambda: None)
    monkeypatch.setattr(cli_runners, "get_line_channel_secret", lambda: "line-secret")
    monkeypatch.setattr(cli_runners, "get_line_channel_access_token", lambda: None)

    cli_runners.setup_messaging_tokens()

    assert captured[0]["step"] == "Step 5/5: Messaging bridges"
    assert captured[0]["title"] == "Configure messaging bridges?"
    assert [value for value, _label, _description in captured[0]["options"]] == [
        "telegram",
        "discord",
        "line",
        "skip",
        "back",
    ]
    assert captured[0]["options"][0] == ("telegram", "Telegram", "configured")
    assert captured[0]["options"][2] == ("line", "LINE", "set channel secret and access token")
    assert captured[0]["options"][3] == ("skip", "Skip messaging setup", "")
    assert captured[0]["options"][-1] == ("back", "← Back to previous step", "")


def test_setup_messaging_tokens_prompts_selected_bridges(monkeypatch):
    choices = iter(["telegram", "discord", "line", "skip"])
    prompted = []

    def fake_select_option(**_kwargs):
        return next(choices)

    monkeypatch.setattr(cli_runners.sys, "stdin", _TtyStub())
    monkeypatch.setattr(cli_runners.sys, "stdout", _TtyStub())
    monkeypatch.setattr(setup_wizard, "_select_option", fake_select_option)
    monkeypatch.setattr(cli_runners, "get_telegram_bot_token", lambda: None)
    monkeypatch.setattr(cli_runners, "get_discord_bot_token", lambda: None)
    monkeypatch.setattr(cli_runners, "get_line_channel_secret", lambda: None)
    monkeypatch.setattr(cli_runners, "get_line_channel_access_token", lambda: None)
    monkeypatch.setattr(
        cli_runners, "_prompt_telegram_bot_token_if_missing", lambda: prompted.append("telegram") or True
    )
    monkeypatch.setattr(cli_runners, "_prompt_discord_bot_token_if_missing", lambda: prompted.append("discord") or True)
    monkeypatch.setattr(cli_runners, "_prompt_line_credentials_if_missing", lambda: prompted.append("line") or True)

    cli_runners.setup_messaging_tokens()

    assert prompted == ["telegram", "discord", "line"]


def test_run_edge_standalone_runs_python_template(monkeypatch, tmp_path):
    setup_path = tmp_path / "yumi_tools" / "python" / "yumi_setup.py"
    setup_path.parent.mkdir(parents=True)
    setup_path.write_text("# generated template\n", encoding="utf-8")
    calls = []

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli_runners.subprocess, "run", lambda cmd, cwd, env: calls.append((cmd, cwd, env)))

    cli.run_edge_standalone(lang=["python"])

    assert len(calls) == 1
    cmd, cwd, env = calls[0]
    assert cmd == [sys.executable, "-m", "yumi_tools.python.yumi_setup"]
    assert cwd == str(tmp_path)
    assert "PATH" in env


def test_run_edge_standalone_runs_multiple_templates(monkeypatch, tmp_path):
    python_setup = tmp_path / "yumi_tools" / "python" / "yumi_setup.py"
    go_main = tmp_path / "yumi_tools" / "go" / "main.go"
    python_setup.parent.mkdir(parents=True)
    go_main.parent.mkdir(parents=True)
    python_setup.write_text("# generated template\n", encoding="utf-8")
    go_main.write_text("package main\n", encoding="utf-8")
    calls = []

    class FakeProcess:
        def poll(self):
            return 0

        def terminate(self):
            return None

        def kill(self):
            return None

    def fake_popen(cmd, cwd, env):
        calls.append((cmd, cwd, env))
        return FakeProcess()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli_runners.subprocess, "Popen", fake_popen)

    cli.run_edge_standalone(lang=["python,go"])

    assert len(calls) == 2
    assert calls[0][0] == [sys.executable, "-m", "yumi_tools.python.yumi_setup"]
    assert calls[0][1] == str(tmp_path)
    assert calls[1][0] == ["go", "run", "."]
    assert calls[1][1] == str(tmp_path / "yumi_tools" / "go")
    assert all("PATH" in env for _cmd, _cwd, env in calls)


def test_print_lan_codes_uses_configured_server_port(monkeypatch, capsys):
    monkeypatch.setenv("YUMI_PORT", "9000")
    monkeypatch.setattr(cli_runners, "_get_lan_ip", lambda: "192.168.1.50")
    monkeypatch.setattr(cli_runners, "get_lan_secret", lambda: None)

    cli_runners._print_lan_codes()

    out = capsys.readouterr().out
    codes = [line.split(":", 1)[1].strip() for line in out.splitlines() if "Code" in line]
    assert codes
    assert all(cli_runners.parse_lan_code(code) == "http://192.168.1.50:9000" for code in codes)


def test_run_server_with_bridge_uses_configured_port(monkeypatch):
    monkeypatch.setenv("YUMI_PORT", "9000")
    monkeypatch.setenv("YUMI_HOST", "127.0.0.1")
    monkeypatch.setattr(cli_runners, "_prompt_telegram_bot_token_if_missing", lambda: True)
    monkeypatch.setattr(cli_runners, "get_telegram_bot_token", lambda: "tg-token")
    monkeypatch.setattr(cli_runners, "_print_banner", lambda *args, **kwargs: None)
    monkeypatch.setattr(cli_runners, "_print_lan_codes", lambda: None)
    monkeypatch.setattr(
        cli_runners,
        "_preflight_models",
        lambda: SimpleNamespace(
            chat_provider="ollama",
            chat_model="m",
            embedding_provider="disabled",
            embedding_model=None,
            voice_owner_id=None,
            voice_wake_word="hi yumi",
            voice_porcupine_access_key=None,
        ),
    )
    waits = []
    monkeypatch.setattr(cli_runners, "_wait_for_server_health", lambda url, timeout=90: waits.append(url) or True)
    popen_calls = []

    class FakeProcess:
        def wait(self, timeout=None):
            return 0

        def terminate(self):
            return None

        def kill(self):
            return None

    def fake_popen(cmd, env):
        popen_calls.append((cmd, env))
        return FakeProcess()

    monkeypatch.setattr(cli_runners.subprocess, "Popen", fake_popen)

    cli_runners.run_server_with_bridges(telegram=True)

    assert waits == ["http://127.0.0.1:9000"]
    assert popen_calls[1][1]["YUMI_SERVER_URL"] == "http://127.0.0.1:9000"


def test_tool_routing_cli_updates_config(monkeypatch, tmp_path, capsys):
    p = tmp_path / "config.json"
    monkeypatch.setattr("yumi.core.features.config.paths.CONFIG_PATH", p)
    monkeypatch.setattr("yumi.core.features.config.store.CONFIG_PATH", p)
    monkeypatch.setattr(cli_runners, "CONFIG_PATH", p)
    monkeypatch.setattr(
        sys, "argv", ["yumi", "--tool-routing", "--edge-tools-limit", "7", "--disable-edge-tool-routing"]
    )
    monkeypatch.setattr(cli, "configure_logging", lambda: None)

    cli.main()

    saved = json.loads(p.read_text(encoding="utf-8"))
    assert saved["edge_tools_retrieval_limit"] == 7
    assert saved["edge_tools_enable_dynamic_routing"] is False
    out = capsys.readouterr().out
    assert "Edge dynamic routing: disabled" in out
    assert "Edge tools per turn:  7" in out


def test_config_cli_writes_full_config(monkeypatch, tmp_path, capsys):
    p = tmp_path / "config.json"
    monkeypatch.setattr("yumi.core.features.config.paths.CONFIG_PATH", p)
    monkeypatch.setattr("yumi.core.features.config.store.CONFIG_PATH", p)
    monkeypatch.setattr(cli_runners, "CONFIG_PATH", p)
    monkeypatch.setattr(sys, "argv", ["yumi", "--config"])
    monkeypatch.setattr(cli, "configure_logging", lambda: None)
    opened = []
    monkeypatch.setattr(cli_runners, "_open_path_with_default_app", lambda path: opened.append(path) or True)

    cli.main()

    saved = json.loads(p.read_text(encoding="utf-8"))
    assert saved["proactive_mode"] == "off"
    assert saved["proactive_enabled"] is False
    assert saved["proactive_quiet_hours"] == "00:30-08:30"
    assert saved["local_timezone"] is None
    assert saved["proactive_check_interval_jitter_ratio"] == 0.15
    assert saved["proactive_unreplied_escalation_jitter_ratio"] == 0.0
    assert saved["proactive_check_in_probability"] == 0.35
    assert opened == [p]
    out = capsys.readouterr().out
    assert "Yumi config written to:" in out
    assert "Opened config file" in out
