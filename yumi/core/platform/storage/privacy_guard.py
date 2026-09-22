"""Cross-process leases for private-data erasure on the shared Nexus volume.

Every user-data request and background turn holds a shared lease. Erasure is
exclusive and fails before changing data if an operation is still running.
The small tombstone lives outside the data being erased; interrupted cleanup
therefore stays closed across restarts instead of exposing a partial result.
"""

from __future__ import annotations

import hashlib
import json
import os
from contextlib import contextmanager

from fastapi import HTTPException


def _paths(owner):
    from yumi.core.features.config.paths import CONFIG_DIR

    root = CONFIG_DIR / "privacy"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = hashlib.sha256(owner.encode()).hexdigest()
    return root / f"{key}.lock", root / f"{key}.json"


def state(owner):
    _, path = _paths(owner)
    if not path.exists():
        return {"status": "active", "generation": 0, "revoked_before": 0}
    return json.loads(path.read_text())


def save_state(owner, value):
    _, path = _paths(owner)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def session_erased(session_id):
    import sqlite3

    from yumi.core.features.config.paths import CONFIG_DIR

    if not session_id.startswith("u_") or "__" not in session_id:
        return False
    owner = session_id[2:].split("__", 1)[0]
    if not owner or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in owner):
        return True
    path = CONFIG_DIR / "users" / owner / "yumi.db"
    if not path.exists():
        return False
    with sqlite3.connect(path) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='erased_sessions'").fetchone():
            return False
        return conn.execute("SELECT 1 FROM erased_sessions WHERE session_id=?", (session_id,)).fetchone() is not None


@contextmanager
def lease(owner, *, exclusive=False, allow_closed=False):
    if not owner or owner == "_local":
        if exclusive:
            raise HTTPException(400, "A private Nexus account is required.")
        yield
        return
    import fcntl

    path, _ = _paths(owner)
    with path.open("a") as lock:
        try:
            fcntl.flock(lock, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise HTTPException(
                423, "Yumi is busy. Wait for replies and tool calls to finish, then try again."
            ) from exc
        try:
            if not allow_closed and state(owner)["status"] != "active":
                raise HTTPException(423, "Your Yumi data is being deleted or your assistant account has been deleted.")
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
