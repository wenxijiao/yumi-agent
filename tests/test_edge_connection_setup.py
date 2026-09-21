"""Destination-first edge setup, especially switching away from Nexus credentials."""

import pytest
from yumi.edge import connection as setup
from yumi.edge.login import EdgeLoginError
from yumi.sdk.python.agent_client import YumiAgent


@pytest.fixture
def workspace(tmp_path):
    env = tmp_path / "yumi_tools" / ".env"
    env.parent.mkdir()
    env.write_text(
        "EDGE_NAME=Test Device\nUNRELATED=keep\nYUMI_RELAY_URL=https://api.yumi.nexus\n"
        "YUMI_ACCESS_TOKEN=yumi_old\nEDGE_LOGIN_NAME=Test Device\nYUMI_EDGE_SERVER=https://api.yumi.nexus\n"
        "YUMI_CONNECTION_CODE=old-code\nBRAIN_URL=https://old.invalid\n"
    )
    return env


def resolved(env, monkeypatch):
    for key in (
        "YUMI_RELAY_URL",
        "YUMI_ACCESS_TOKEN",
        "YUMI_EDGE_SERVER",
        "YUMI_CONNECTION_CODE",
        "BRAIN_URL",
        "EDGE_NAME",
    ):
        monkeypatch.delenv(key, raising=False)
    return YumiAgent(env_path=str(env))._resolve_connection()


def test_interactive_destination_then_local_auth_clears_old_nexus(workspace, monkeypatch):
    from yumi.core.features.config import setup_wizard as wizard

    calls = []

    def select(**kwargs):
        calls.append(kwargs)
        return "server" if len(calls) == 1 else "none"

    monkeypatch.setattr(wizard, "_select_option", select)
    monkeypatch.setattr(wizard, "_framed_prompt", lambda *a, **kw: "")
    monkeypatch.setattr(setup, "sign_in", lambda *a, **kw: pytest.fail("Local server must not open Identity"))
    label = setup.configure_connection(str(workspace), True)
    assert [o[0] for o in calls[0]["options"]] == ["keep", "nexus", "server", "skip"]
    assert calls[1]["title"] == "Does this server require sign-in?"
    assert "127.0.0.1:8000" in label
    actual = resolved(workspace, monkeypatch)
    assert actual.mode == "direct" and actual.base_url == "ws://127.0.0.1:8000/ws/edge"
    assert not actual.access_token
    assert setup.read_setting(str(workspace), "UNRELATED") == "keep"
    assert not setup.read_setting(str(workspace), "YUMI_EDGE_SERVER")
    assert not setup.read_setting(str(workspace), "BRAIN_URL")


@pytest.mark.parametrize(
    "address,expected",
    [
        ("http://192.168.1.30:8000", "ws://192.168.1.30:8000/ws/edge"),
        ("https://yumi.example/proxy/", "wss://yumi.example/proxy/ws/edge"),
        ("ws://localhost:9000/ws/edge", "ws://localhost:9000/ws/edge"),
        ("http://[::1]:8000", "ws://[::1]:8000/ws/edge"),
    ],
)
def test_explicit_server_flag_selects_direct_connection(workspace, monkeypatch, address, expected):
    setup.configure_connection(str(workspace), False, server=address)
    assert resolved(workspace, monkeypatch).base_url == expected


def test_lan_code_selects_its_address_and_clears_stale_host(workspace, monkeypatch):
    from yumi.core.platform.security.connection import issue_lan_code

    code = issue_lan_code("http://192.168.1.30:8123")
    setup.configure_connection(str(workspace), False, target="server", server=code)
    assert resolved(workspace, monkeypatch).base_url == "ws://192.168.1.30:8123/ws/edge"


def test_nexus_prompts_for_browser_or_code_after_destination(workspace, monkeypatch):
    from yumi.core.features.config import setup_wizard as wizard

    calls = []

    def select(**kwargs):
        calls.append(kwargs)
        return "nexus" if len(calls) == 1 else "browser"

    monkeypatch.setattr(wizard, "_select_option", select)
    seen = []
    monkeypatch.setattr(
        setup, "sign_in", lambda *args, **kwargs: seen.append((args, kwargs)) or "alice@example.invalid"
    )
    assert "alice@example.invalid" in setup.configure_connection(str(workspace), True, open_browser=False)
    assert [o[0] for o in calls[1]["options"]] == ["browser", "code"]
    assert seen[0][1] == {"server": setup.NEXUS_SERVER, "open_browser": False}


def test_account_code_selects_new_host_and_clears_old_token(workspace, monkeypatch):
    monkeypatch.setenv("YUMI_CONNECTION_CODE", "/link new-code")
    setup.configure_connection(str(workspace), False, target="nexus", method="code")
    assert setup.read_setting(str(workspace), "YUMI_CONNECTION_CODE") == "new-code"
    assert setup.read_setting(str(workspace), "YUMI_EDGE_SERVER") == setup.NEXUS_SERVER
    assert not setup.read_setting(str(workspace), "YUMI_ACCESS_TOKEN")


def test_custom_device_token_uses_custom_host(workspace, monkeypatch):
    monkeypatch.setenv("YUMI_ACCESS_TOKEN", "yumi_custom_credential")
    setup.configure_connection(str(workspace), False, target="server", server="https://custom.example", method="token")
    actual = resolved(workspace, monkeypatch)
    assert actual.base_url == "https://custom.example"
    assert actual.access_token == "yumi_custom_credential"
    assert not setup.read_setting(str(workspace), "YUMI_CONNECTION_CODE")


@pytest.mark.parametrize(
    "address",
    [
        "ftp://host",
        "https://user:secret@host",
        "http://host:invalid",
        "http://host:0",
        "https://host/?access_token=secret",
        "http://host\nEDGE_NAME=other",
    ],
)
def test_invalid_address_never_changes_saved_credentials(workspace, address):
    before = workspace.read_bytes()
    with pytest.raises((EdgeLoginError, ValueError)):
        setup.configure_connection(str(workspace), False, target="server", server=address)
    assert workspace.read_bytes() == before


def test_skip_preserves_configuration(workspace):
    before = workspace.read_bytes()
    setup.configure_connection(str(workspace), False, target="skip")
    assert workspace.read_bytes() == before


def test_missing_code_is_explicit_error_and_preserves_connection(workspace, monkeypatch):
    monkeypatch.delenv("YUMI_CONNECTION_CODE", raising=False)
    before = workspace.read_bytes()
    with pytest.raises(EdgeLoginError, match="required"):
        setup.configure_connection(str(workspace), False, target="nexus", method="code")
    assert workspace.read_bytes() == before


def test_renamed_device_does_not_offer_invalid_saved_token(workspace, monkeypatch):
    from yumi.core.features.config import setup_wizard as wizard

    workspace.write_text(workspace.read_text().replace("EDGE_NAME=Test Device", "EDGE_NAME=Different Device"))

    def select(**kwargs):
        assert "keep" not in [o[0] for o in kwargs["options"]]
        return "skip"

    monkeypatch.setattr(wizard, "_select_option", select)
    setup.configure_connection(str(workspace), True)
