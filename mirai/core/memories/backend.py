"""LanceDB connection + table primitives shared by every memory repository.

Owns:

* the process-wide LanceDB connection cache (one per ``db_dir``),
* schema-agnostic table helpers (``has_table``, ``open_table``, …),
* time / where-clause / SQL-escape helpers used by every CRUD path.

This is the substrate for the Repository classes in :mod:`mirai.core.memories.repos`.
The :class:`~mirai.core.memories.memory.Memory` façade keeps the legacy
``_has_table`` / ``_open_table`` / ``_build_where_clause`` private aliases as
delegates so external consumers (``context.py``, ``storage.py``, ``writer.py``)
keep working without changes.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

import lancedb


class LanceDBBackend:
    """Process-wide LanceDB connection + low-level helpers.

    Re-uses one ``lancedb.connect(db_dir)`` per process — LanceDB caches
    table handles internally, so opening many ``Memory`` instances against
    the same directory is cheap.
    """

    _shared_db: dict[str, object] = {}
    _init_lock = threading.Lock()

    def __init__(self, db_dir: str) -> None:
        self.db_dir = db_dir
        with LanceDBBackend._init_lock:
            if db_dir not in LanceDBBackend._shared_db:
                LanceDBBackend._shared_db[db_dir] = lancedb.connect(db_dir)
        self.db = LanceDBBackend._shared_db[db_dir]

    # ── table existence ────────────────────────────────────────────────────

    def list_table_names(self, db=None) -> set[str]:
        target_db = db or self.db
        list_tables = getattr(target_db, "list_tables", None)
        if callable(list_tables):
            result = list_tables()
            names = getattr(result, "tables", result)
            return {str(name) for name in names}
        return {str(name) for name in target_db.table_names()}

    def has_table(self, table_name: str, db=None) -> bool:
        return table_name in self.list_table_names(db)

    def open_table(self, table_name: str):
        return self.db.open_table(table_name)

    # ── timestamp helpers ──────────────────────────────────────────────────

    @staticmethod
    def format_timestamp() -> str:
        # Produce UTC so parse_timestamp_num — which interprets the string as UTC —
        # round-trips correctly. Prompt-side displays format the timestamp_num
        # number with the user's tz, so the human-facing wall clock is unaffected.
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %A")

    @staticmethod
    def current_timestamp_num() -> int:
        return int(datetime.now(timezone.utc).timestamp() * 1000)

    @staticmethod
    def parse_timestamp_num(timestamp_num, timestamp, fallback) -> int:
        if timestamp_num is not None:
            return int(timestamp_num)
        try:
            parsed = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S %A")
            return int(parsed.replace(tzinfo=timezone.utc).timestamp() * 1000)
        except (TypeError, ValueError):
            return fallback

    # ── SQL escaping & where-clauses ───────────────────────────────────────

    @staticmethod
    def escape_where_value(value: str) -> str:
        return value.replace("\\", "\\\\").replace("'", "''")

    @classmethod
    def build_where_clause(cls, field: str, value: str) -> str:
        return f"{field} = '{cls.escape_where_value(value)}'"

    # ── table init guard ───────────────────────────────────────────────────

    _initialized_dirs: set[str] = set()

    def claim_initialization(self) -> bool:
        """Return True iff this process has not yet initialised ``db_dir``.

        Memory's constructor runs schema migrations exactly once per
        directory; subsequent ``Memory(...)`` instantiations bypass the work.
        """
        with LanceDBBackend._init_lock:
            if self.db_dir in LanceDBBackend._initialized_dirs:
                return False
            LanceDBBackend._initialized_dirs.add(self.db_dir)
            return True


__all__ = ["LanceDBBackend"]
