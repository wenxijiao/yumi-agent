from collections import OrderedDict

import pytest
from yumi.core.platform.tools import session_tools as cache


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setattr(cache, "_RECENT", OrderedDict())


def test_reuse_is_account_and_session_scoped():
    cache.remember_tools("alice", "same-session", ["play"])
    assert cache.recent_tools("alice", "same-session", {"play"}) == ["play"]
    assert cache.recent_tools("bob", "same-session", {"play"}) == []
    assert cache.recent_tools("alice", "other-session", {"play"}) == []


def test_expiry_and_revocation_are_not_refreshed_by_listing(monkeypatch):
    now = [0]
    monkeypatch.setattr(cache, "monotonic", lambda: now[0])
    cache.remember_tools("alice", "s", ["play", "search"])
    now[0] = cache._TTL_SECONDS - 1
    assert cache.recent_tools("alice", "s", {"play"}) == ["play"]
    assert cache.recent_tools("alice", "s", {"play", "search"}) == ["play"]
    now[0] += 1
    assert cache.recent_tools("alice", "s", {"play"}) == []


def test_limits_and_session_reset(monkeypatch):
    from yumi.core.platform.tools.routing import clear_session_edges

    monkeypatch.setattr(cache, "_MAX_TOOLS", 2)
    monkeypatch.setattr(cache, "_MAX_SESSIONS", 2)
    cache.remember_tools("alice", "old", ["one"])
    cache.remember_tools("alice", "s", ["one", "two", "three", "browse_app_tools"])
    cache.remember_tools("bob", "s", ["other"])
    assert cache.recent_tools("alice", "old", {"one"}) == []
    assert cache.recent_tools("alice", "s", {"one", "two", "three"}) == ["three", "two"]
    clear_session_edges("s")
    assert cache.recent_tools("alice", "s", {"one", "two", "three"}) == []
    assert cache.recent_tools("bob", "s", {"other"}) == []
