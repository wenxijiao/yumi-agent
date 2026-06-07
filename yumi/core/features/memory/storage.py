"""Small LanceDB table helpers used by memory submodules."""

from __future__ import annotations

from typing import Any


def table_exists(memory: Any, table_name: str) -> bool:
    return memory._has_table(table_name)


def open_table(memory: Any, table_name: str):
    return memory.db.open_table(table_name)


def add_row(memory: Any, table_name: str, row: dict) -> None:
    """Append *row*, creating *table_name* lazily on first write."""

    if table_exists(memory, table_name):
        open_table(memory, table_name).add([row])
        return
    try:
        memory.db.create_table(table_name, data=[row])
    except Exception:
        open_table(memory, table_name).add([row])


def replace_row(memory: Any, table_name: str, key_field: str, key_value: str, row: dict) -> None:
    """Replace a single row identified by *key_field*."""

    if table_exists(memory, table_name):
        table = open_table(memory, table_name)
        table.delete(memory._build_where_clause(key_field, key_value))
        table.add([row])
        return
    try:
        memory.db.create_table(table_name, data=[row])
    except Exception:
        table = open_table(memory, table_name)
        table.delete(memory._build_where_clause(key_field, key_value))
        table.add([row])


def query_rows(
    memory: Any,
    table_name: str,
    *,
    ordering_field_name: str | None = None,
    where_clause: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    if not table_exists(memory, table_name):
        return []
    table = open_table(memory, table_name)
    query = table.search(query=None, ordering_field_name=ordering_field_name)
    if where_clause:
        query = query.where(where_clause)
    if limit is not None:
        query = query.limit(limit)
    return query.to_list()
