import os
import stat

import pytest
from yumi.edge import login


def fake_start():
    return {
        "device_code": "private-terminal-secret",
        "user_code": "ABCD-EFGH",
        "verification_uri_complete": "https://id.yumi.nexus/?edge_code=ABCD-EFGH",
        "interval": 1,
        "expires_in": 10,
    }


def test_browser_login_saves_private_env_then_acknowledges(tmp_path, monkeypatch):
    path = tmp_path / "yumi_tools" / ".env"
    path.parent.mkdir()
    path.write_text("UNRELATED=keep\nYUMI_CONNECTION_CODE=old\nYUMI_ACCESS_TOKEN=old\n")
    requests, messages, opened = [], [], []

    def request(server, action, body):
        requests.append((action, body))
        if action == "start":
            return fake_start()
        if action == "token":
            return {
                "status": "approved",
                "access_token": "yumi_device_token",
                "account": "alice@example.invalid",
                "edge_name": "Laptop",
            }
        if action == "ack":
            assert "yumi_device_token" in path.read_text()
        return {"status": "ok"}

    monkeypatch.setattr(login, "_request", request)
    monkeypatch.setattr(login.time, "sleep", lambda _: None)
    monkeypatch.delenv("SSH_CONNECTION", raising=False)
    monkeypatch.delenv("SSH_TTY", raising=False)
    monkeypatch.setattr(login.webbrowser, "open", opened.append)
    assert login.sign_in(str(path), "Laptop", emit=messages.append) == "alice@example.invalid"
    assert opened == [fake_start()["verification_uri_complete"]]
    assert "UNRELATED=keep" in path.read_text()
    assert "YUMI_CONNECTION_CODE=\n" in path.read_text()
    assert "YUMI_RELAY_URL=https://api.yumi.nexus" in path.read_text()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert ".env" in (path.parent / ".gitignore").read_text()
    assert [r[0] for r in requests] == ["start", "token", "ack"]
    assert all("yumi_device_token" not in line and "private-terminal-secret" not in line for line in messages)


def test_ssh_pending_then_success_without_browser(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setenv("SSH_CONNECTION", "test")
    monkeypatch.setattr(login.webbrowser, "open", lambda _: pytest.fail("Must not open remote browser"))
    monkeypatch.setattr(login.time, "sleep", lambda _: None)

    def request(server, action, body):
        calls.append(action)
        if action == "start":
            return fake_start()
        if action == "token":
            if calls.count("token") == 1:
                return {"status": "authorization_pending"}
            return {"status": "approved", "access_token": "yumi_device", "edge_name": "Pi"}
        return {}

    monkeypatch.setattr(login, "_request", request)
    login.sign_in(str(tmp_path / ".env"), "Pi", emit=lambda _: None)
    assert calls == ["start", "token", "token", "ack"]


def test_interrupt_cancels_request_and_preserves_existing_credentials(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("YUMI_ACCESS_TOKEN=existing\n")
    calls = []

    def request(server, action, body):
        calls.append(action)
        return fake_start() if action == "start" else {}

    def interrupt(_):
        raise KeyboardInterrupt

    monkeypatch.setattr(login, "_request", request)
    monkeypatch.setattr(login.time, "sleep", interrupt)
    with pytest.raises(KeyboardInterrupt):
        login.sign_in(str(path), "Laptop", open_browser=False, emit=lambda _: None)
    assert calls == ["start", "cancel"]
    assert path.read_text() == "YUMI_ACCESS_TOKEN=existing\n"


def test_failure_does_not_leak_secrets_or_follow_redirects(monkeypatch):
    class Redirect:
        status_code = 307

    def post(url, **kwargs):
        assert kwargs["allow_redirects"] is False
        return Redirect()

    monkeypatch.setattr(login.requests, "post", post)
    with pytest.raises(login.EdgeLoginError):
        login._request("https://api.yumi.nexus", "token", {"device_code": "secret"})


def test_rejects_insecure_servers_and_symlink_credentials(tmp_path):
    for server in ["http://example.com", "https://user:password@example.com", "https://example.com?redirect=other"]:
        with pytest.raises(login.EdgeLoginError):
            login.sign_in(str(tmp_path / ".env"), "Laptop", server=server)
    target = tmp_path / "private"
    target.write_text("untouched")
    path = tmp_path / ".env"
    os.symlink(target, path)
    with pytest.raises(login.EdgeLoginError):
        login.save_credentials(str(path), server="https://api.yumi.nexus", edge_name="Laptop", token="yumi_test")
    assert target.read_text() == "untouched"


def test_poll_network_failure_retries_same_request_with_backoff(tmp_path, monkeypatch):
    calls, sleeps = [], []
    monkeypatch.setattr(login.time, "sleep", sleeps.append)

    def request(server, action, body):
        calls.append(action)
        if action == "start":
            return fake_start()
        if action == "token" and calls.count("token") == 1:
            raise login._RetryableLoginError("offline")
        if action == "token":
            return {"status": "approved", "access_token": "yumi_device", "edge_name": "Pi"}
        return {}

    monkeypatch.setattr(login, "_request", request)
    login.sign_in(str(tmp_path / ".env"), "Pi", open_browser=False, emit=lambda _: None)
    assert calls == ["start", "token", "token", "ack"]
    assert sleeps == [1, 2]
