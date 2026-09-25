"""Bounded, account/session-scoped reuse of discovered or successfully used names.

No schemas, query text, results or authorization decisions are cached here.
Routing resolves names against a fresh permission-scoped catalog every time.
"""

from collections import OrderedDict
from threading import Lock
from time import monotonic

_TTL_SECONDS = 30 * 60
_MAX_SESSIONS = 4000
_MAX_TOOLS = 24
_RECENT: OrderedDict[tuple[str, str], OrderedDict[str, float]] = OrderedDict()
_LOCK = Lock()
_DISCOVERY = {"discover_app_tools", "browse_app_tools"}


def remember_tools(owner: str, session_id: str, names: list[str]) -> None:
    if not owner or not session_id:
        return
    names = [name for name in names if name and name not in _DISCOVERY]
    if not names:
        return
    now = monotonic()
    key = (owner, session_id)
    with _LOCK:
        recent = _RECENT.setdefault(key, OrderedDict())
        for name in names:
            recent[name] = now
            recent.move_to_end(name)
        while len(recent) > _MAX_TOOLS:
            recent.popitem(last=False)
        _RECENT.move_to_end(key)
        while len(_RECENT) > _MAX_SESSIONS:
            _RECENT.popitem(last=False)


def recent_tools(owner: str, session_id: str, visible_names: set[str]) -> list[str]:
    now = monotonic()
    key = (owner, session_id)
    with _LOCK:
        recent = _RECENT.get(key)
        if recent is None:
            return []
        for name, used in list(recent.items()):
            if name not in visible_names or now - used >= _TTL_SECONDS:
                del recent[name]
        if not recent:
            _RECENT.pop(key, None)
            return []
        return list(reversed(recent))


def clear_session_tools(session_id: str) -> None:
    with _LOCK:
        for key in list(_RECENT):
            if key[1] == session_id:
                del _RECENT[key]
