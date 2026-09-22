"""Account-scoped personal assistant state, independent of the vector index.

The active conversation pointer is a transactional compare-and-swap. Session ids
remain opaque storage segments; resetting never deletes messages or memories.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timedelta, timezone

from yumi.core.platform.plugins.identity import SINGLE_USER_ID
from yumi.core.platform.storage.sqlite_store import SQLiteStore, _event_row_to_message


class StaleRevision(ValueError):
    pass


def is_personal_session(session_id: str) -> bool:
    return session_id.split("__", 1)[-1].startswith("personal_")


def is_group_session(session_id: str) -> bool:
    return session_id.split("__", 1)[-1].startswith("group_")


class AssistantStore:
    def __init__(self, sqlite: SQLiteStore, owner: str):
        self.sqlite = sqlite
        self.owner = owner
        self.namespace = f"assistant:{owner}"

    def _read(self, conn, key, default):
        row = conn.execute(
            "SELECT value_json FROM settings WHERE namespace=? AND key=?", (self.namespace, key)
        ).fetchone()
        return json.loads(row[0]) if row else default

    def _write(self, conn, key, value):
        conn.execute(
            """INSERT INTO settings(namespace,key,value_json,updated_at) VALUES(?,?,?,?)
            ON CONFLICT(namespace,key) DO UPDATE SET value_json=excluded.value_json,
            updated_at=excluded.updated_at""",
            (self.namespace, key, json.dumps(value), datetime.now(timezone.utc).isoformat()),
        )

    def get(self, key: str, default=None):
        with self.sqlite.connect() as conn:
            return self._read(conn, key, default)

    def put(self, key: str, value):
        with self.sqlite.connect() as conn:
            self._write(conn, key, value)
        return value

    def current(self, qualify) -> dict:
        with self.sqlite.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            state = self._read(conn, "state", None)
            if state is None:
                state = {
                    "session_id": qualify(f"personal_{uuid.uuid4().hex}"),
                    "revision": 1,
                    "started_at": datetime.now(timezone.utc).isoformat(),
                }
                self._write(conn, "state", state)
            return state

    def reset(self, expected_revision: int, qualify) -> dict:
        with self.sqlite.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = self._read(conn, "state", None)
            if not current or current["revision"] != expected_revision:
                raise StaleRevision("Conversation changed on another device. Refresh and try again.")
            state = {
                "session_id": qualify(f"personal_{uuid.uuid4().hex}"),
                "revision": current["revision"] + 1,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
            self._write(conn, "state", state)
            return state

    def snapshot(self, state: dict, *, limit: int = 100, before: int | None = None) -> dict:
        clauses = ["e.deleted_at IS NULL", "e.session_id=?", "e.event_type IN ('user_message','assistant_message')"]
        params = [state["session_id"]]
        if before is not None:
            clauses.append("e.seq < ?")
            params.append(before)
        with self.sqlite.connect() as conn:
            rows = conn.execute(
                f"SELECT e.* FROM events e WHERE {' AND '.join(clauses)} ORDER BY seq DESC LIMIT ?",
                [*params, limit + 1],
            ).fetchall()
        messages = [_event_row_to_message(r) for r in reversed(rows[:limit])]
        for message in messages:
            if message["role"] == "assistant" and message["turn_id"]:
                trace = self.sqlite.get_turn_trace(message["turn_id"]) or {}
                if trace.get("session_id") == message["session_id"]:
                    message["duration_ms"] = trace.get("duration_ms")
                    message["confirmation_wait_ms"] = trace.get("confirmation_wait_ms")
                results = [result for step in trace.get("rounds", []) for result in step.get("tool_results", [])]
                message["tool_events"] = [
                    {
                        "status": result.get("status", "success"),
                        "content": f"{result.get('tool', 'Tool')}: {str(result.get('result_preview') or result.get('result') or result.get('status', ''))[:800]}",
                    }
                    for result in results
                ]
        return {**state, "messages": messages, "has_more": len(rows) > limit}

    def history(
        self,
        *,
        prefix: str | None = None,
        query: str = "",
        channel: str = "",
        before: int | None = None,
        after: int | None = None,
        anchor: int | None = None,
        limit: int = 50,
    ) -> dict:
        clauses = [
            "e.deleted_at IS NULL",
            "COALESCE(s.status,'active') != 'deleted'",
            "e.event_type IN ('user_message','assistant_message')",
            "e.session_id NOT LIKE '%group\\_%' ESCAPE '\\'",
        ]
        params: list = []
        if prefix:
            clauses.append("substr(e.session_id,1,?)=?")
            params.extend([len(prefix), prefix])
        if query.strip():
            clauses.append("instr(lower(e.content), lower(?)) > 0")
            params.append(query.strip())
        if channel:
            clauses.append(
                "COALESCE(json_extract(e.metadata_json,'$.channel'), CASE "
                "WHEN e.session_id LIKE '%tg\\_%' ESCAPE '\\' THEN 'telegram' "
                "WHEN e.session_id LIKE '%dc\\_%' ESCAPE '\\' THEN 'discord' "
                "WHEN s.channel IN ('chat','app') OR s.channel IS NULL THEN 'app' ELSE s.channel END)=?"
            )
            params.append(channel)
        if sum(value is not None for value in (before, after, anchor)) > 1:
            raise ValueError("Choose one history cursor")
        base = " AND ".join(clauses)
        with self.sqlite.connect() as conn:
            if anchor is not None:
                pivot = conn.execute(
                    f"SELECT MAX(e.seq) FROM events e LEFT JOIN sessions s ON s.session_id=e.session_id WHERE {base} AND e.timestamp_num < ?",
                    [*params, anchor],
                ).fetchone()[0]
                if pivot is None:
                    after = 0
                else:
                    before = pivot + 1
            page_clauses = list(clauses)
            page_params = list(params)
            if before is not None:
                page_clauses.append("e.seq < ?")
                page_params.append(before)
            if after is not None:
                page_clauses.append("e.seq > ?")
                page_params.append(after)
            order = "ASC" if after is not None else "DESC"
            rows = conn.execute(
                f"""SELECT e.*, COALESCE(json_extract(t.summary_json, '$.tool_call_count'),0) AS tool_call_count, json_extract(t.summary_json, '$.duration_ms') AS duration_ms
                FROM events e LEFT JOIN sessions s ON s.session_id=e.session_id
                LEFT JOIN turn_traces t ON t.turn_id=e.turn_id AND t.session_id=e.session_id
                WHERE {" AND ".join(page_clauses)} ORDER BY e.seq {order} LIMIT ?""",
                [*page_params, limit],
            ).fetchall()
            if after is not None:
                rows = list(reversed(rows))

            def exists(operator, seq):
                return (
                    conn.execute(
                        f"SELECT 1 FROM events e LEFT JOIN sessions s ON s.session_id=e.session_id WHERE {base} AND e.seq {operator} ? LIMIT 1",
                        [*params, seq],
                    ).fetchone()
                    is not None
                )

            older = rows[-1]["seq"] if rows and exists("<", rows[-1]["seq"]) else None
            newer = rows[0]["seq"] if rows and exists(">", rows[0]["seq"]) else None
        messages = [_event_row_to_message(r) for r in rows]
        for message, row in zip(messages, rows):
            message["tool_call_count"] = row["tool_call_count"] if message["role"] == "assistant" else 0
            message["duration_ms"] = row["duration_ms"] if message["role"] == "assistant" else None
        return {"messages": messages, "next_before": older, "next_after": newer}

    def message_detail(self, message):
        """Read only this message's public response/reasoning and tool activity.

        The caller checks ownership first. Never return the trace's model input,
        system prompts or other messages; even a malformed turn link must not
        allow activity from a different session to appear here.
        """
        detail = {**message, "tool_calls": [], "activity_available": False}
        if message["role"] != "assistant" or not message.get("turn_id"):
            return detail
        trace = self.sqlite.get_turn_trace(message["turn_id"])
        if not trace or trace.get("session_id") != message["session_id"]:
            return detail
        return {
            **detail,
            **self.turn_activity(trace),
            "thought": "\n\n".join(
                str(r.get("reasoning_text") or "")
                for r in trace.get("rounds", [])
                if str(r.get("reasoning_text") or "").strip()
            )
            or message.get("thought", ""),
        }

    def turn_activity(self, trace):
        """Owner-visible round output and tool input/output, never hidden prompts."""
        from yumi.core.platform.storage.tool_run_store import ToolRunStore
        from yumi.core.platform.tools.trace import _truncate_args, _truncate_result_preview

        message = {"turn_id": trace["id"], "session_id": trace["session_id"]}
        detail = {"activity_available": True, "tool_calls": [], "rounds": [], "status": trace.get("status")}
        for key in ("duration_ms", "confirmation_wait_ms", "first_response_ms"):
            detail[key] = trace.get(key)
        reasoning = [str(r.get("reasoning_text") or "") for r in trace.get("rounds", [])]
        detail["thought"] = "\n\n".join(r for r in reasoning if r.strip()) or message.get("thought", "")
        runs = ToolRunStore(self.sqlite, self.owner)
        for number, step in enumerate(trace.get("rounds", []), 1):
            first_call = len(detail["tool_calls"])
            calls = [c for c in step.get("tool_calls", []) if isinstance(c, dict)]
            results = [r for r in step.get("tool_results", []) if isinstance(r, dict)]
            used = set()
            for index, call in enumerate(calls):
                fn = call.get("function") if isinstance(call.get("function"), dict) else {}
                result_index = next(
                    (
                        i
                        for i, r in enumerate(results)
                        if i not in used and call.get("id") and r.get("call_id") == call["id"]
                    ),
                    None,
                )
                result = results[result_index] if result_index is not None else {}
                if result_index is not None:
                    used.add(result_index)
                saved = runs.get(f"ai-{message['turn_id']}-{call.get('id')}") or {}
                # IDs are globally unique, but still verify the message linkage.
                if saved.get("session_id") != message["session_id"]:
                    saved = {}
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except ValueError:
                        pass
                detail["tool_calls"].append(
                    {
                        "id": call.get("id") or f"{step.get('index', 0)}-{index}",
                        "name": result.get("resolved_tool") or fn.get("name") or result.get("tool", "Tool"),
                        "arguments": _truncate_args(saved.get("arguments", args)),
                        "result": _truncate_result_preview(saved.get("result", result.get("result_preview", ""))),
                        "status": saved.get("status", result.get("status", "unknown")),
                        "duration_ms": saved.get("duration_ms", result.get("duration_ms")),
                        "approval": saved.get("approval", "legacy"),
                        "action_summary": saved.get("action_summary"),
                        "edge": result.get("edge"),
                    }
                )
            for index, result in enumerate(results):
                if index in used:
                    continue
                detail["tool_calls"].append(
                    {
                        "id": result.get("call_id") or f"result-{index}",
                        "name": result.get("resolved_tool") or result.get("tool", "Tool"),
                        "arguments": None,
                        "result": _truncate_result_preview(result.get("result_preview", "")),
                        "status": result.get("status", "unknown"),
                        "duration_ms": result.get("duration_ms"),
                        "approval": "legacy",
                        "edge": result.get("edge"),
                    }
                )
            detail["rounds"].append(
                {
                    "index": step.get("index", number),
                    "model": step.get("model", ""),
                    "duration_ms": step.get("duration_ms"),
                    "response_text": str(step.get("response_text") or ""),
                    "reasoning_text": str(step.get("reasoning_text") or ""),
                    "finish_reason": (step.get("finish") or {}).get("reason"),
                    "usage": step.get("usage") or {},
                    "tool_calls": detail["tool_calls"][first_call:],
                    "events": [
                        {"content": item.get("label", ""), "status": item.get("status", "unknown")}
                        for item in trace.get("timeline", [])
                        if item.get("round") == step.get("index", number)
                        and item.get("kind") in ("tool_status", "error", "confirmation")
                    ],
                }
            )
        return detail

    def reclassify_memory(self, memory_id: str, kind: str) -> dict | None:
        """Change only a saved item's category, preserving content and source links."""
        with self.sqlite.connect() as conn:
            changed = conn.execute(
                "UPDATE memories SET kind=?, updated_at=?, revision=revision+1 WHERE id=? AND deleted_at IS NULL",
                (kind, datetime.now(timezone.utc).isoformat(), memory_id),
            ).rowcount
        return next((row for row in self.memories() if row["id"] == memory_id), None) if changed else None

    def memories(self, *, include_deleted=False) -> list[dict]:
        with self.sqlite.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memories WHERE kind != 'tool_observation' "
                + ("" if include_deleted else "AND deleted_at IS NULL ")
                + "ORDER BY updated_at DESC"
            ).fetchall()
        return [
            {
                **dict(r),
                "source_message_ids": json.loads(r["source_event_ids_json"]),
                "metadata": json.loads(r["metadata_json"]),
            }
            for r in rows
            if not is_group_session(r["session_id"])
        ]

    def usage(self, days: int) -> dict:
        from yumi.core.platform.storage.usage_details import present_usage, summarize_usage

        start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)
        with self.sqlite.connect() as conn:
            rows = conn.execute(
                """SELECT * FROM token_usage WHERE created_at_num>=?
                AND (owner_user_id=? OR (owner_user_id='' AND ?)) ORDER BY created_at_num DESC""",
                (int(start.timestamp() * 1000), self.owner, self.owner in ("", SINGLE_USER_ID)),
            ).fetchall()
        totals = {k: sum(r[k] for r in rows) for k in ("prompt_tokens", "completion_tokens", "total_tokens")}
        daily = {}
        for row in rows:
            day = datetime.fromtimestamp(row["created_at_num"] / 1000, timezone.utc).date().isoformat()
            daily[day] = daily.get(day, 0) + row["total_tokens"]
        return {
            **totals,
            "days": days,
            "timezone": "UTC",
            "daily": daily,
            "recent": [present_usage(r) for r in rows[:30]],
            "cache": summarize_usage(rows),
        }

    def monthly_usage(self, month: str, timezone_name: str) -> dict:
        from calendar import monthrange
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        from yumi.core.platform.storage.usage_details import present_usage, summarize_usage

        try:
            zone = ZoneInfo(timezone_name)
            year, number = map(int, month.split("-"))
            if not 1970 <= year <= 2200:
                raise ValueError("Month is out of range")
            start = datetime(year, number, 1, tzinfo=zone)
            end = datetime(year + (number == 12), number % 12 + 1, 1, tzinfo=zone)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("Provide a valid month and IANA timezone") from exc
        with self.sqlite.connect() as conn:
            rows = conn.execute(
                "SELECT rowid AS ledger_seq, * FROM token_usage WHERE created_at_num >= ? AND created_at_num < ? "
                "AND (owner_user_id=? OR (owner_user_id='' AND ?)) ORDER BY created_at_num DESC",
                (
                    int(start.timestamp() * 1000),
                    int(end.timestamp() * 1000),
                    self.owner,
                    self.owner in ("", SINGLE_USER_ID),
                ),
            ).fetchall()
        keys = ("prompt_tokens", "completion_tokens", "total_tokens")
        totals = {key: 0 for key in keys}
        by_day = {
            f"{month}-{day:02d}": {**totals, "requests": 0, "entry_count": 0, "models": {}, "recent": []}
            for day in range(1, monthrange(year, number)[1] + 1)
        }
        models = {}
        by_kind = {}
        day_rows = {day: [] for day in by_day}
        for row in rows:
            day = datetime.fromtimestamp(row["created_at_num"] / 1000, zone).date().isoformat()
            item = by_day[day]
            day_rows[day].append(row)
            for key in keys:
                totals[key] += row[key]
                item[key] += row[key]
            item["requests"] += int(row["usage_kind"] == "chat")
            item["entry_count"] += 1
            by_kind[row["usage_kind"]] = by_kind.get(row["usage_kind"], 0) + row["total_tokens"]
            name = row["model"] or "Unknown model"
            item["models"][name] = item["models"].get(name, 0) + row["total_tokens"]
            models[name] = models.get(name, 0) + row["total_tokens"]
            if len(item["recent"]) < 10:
                item["recent"].append(present_usage(row))
        for day, item in by_day.items():
            item["cache"] = summarize_usage(day_rows[day])
        return {
            **totals,
            "cache": summarize_usage(rows),
            "month": month,
            "snapshot_seq": max((row["ledger_seq"] for row in rows), default=0),
            "timezone": timezone_name,
            "requests": sum(row["usage_kind"] == "chat" for row in rows),
            "entry_count": len(rows),
            "by_kind": by_kind,
            "daily": {day: item["total_tokens"] for day, item in by_day.items()},
            "by_day": by_day,
            "models": models,
            "recent": [present_usage(row) for row in rows[:30]],
        }

    def usage_requests(
        self, day: str, timezone_name: str, *, before: str = "", limit: int = 50, snapshot: int | None = None
    ) -> dict:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            date = datetime.strptime(day, "%Y-%m-%d")
            start = date.replace(tzinfo=ZoneInfo(timezone_name))
            end = start + timedelta(days=1)
            cursor = before.split(":", 1) if before else None
            cursor_time = int(cursor[0]) if cursor else 0
            if cursor and len(cursor) != 2:
                raise ValueError("Invalid cursor")
        except (ValueError, ZoneInfoNotFoundError) as exc:
            raise ValueError("Provide a valid day, timezone and cursor") from exc
        clauses = ["created_at_num >= ?", "created_at_num < ?", "(owner_user_id=? OR (owner_user_id='' AND ?))"]
        params = [
            int(start.timestamp() * 1000),
            int(end.timestamp() * 1000),
            self.owner,
            self.owner in ("", SINGLE_USER_ID),
        ]
        if snapshot is not None:
            clauses.append("rowid <= ?")
            params.append(snapshot)
        if cursor:
            clauses.append("(created_at_num < ? OR (created_at_num = ? AND id < ?))")
            params.extend([cursor_time, cursor_time, cursor[1]])
        with self.sqlite.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM token_usage WHERE {' AND '.join(clauses)} ORDER BY created_at_num DESC, id DESC LIMIT ?",
                [*params, limit + 1],
            ).fetchall()
        from yumi.core.platform.storage.usage_details import present_usage

        page = [present_usage(row) for row in rows[:limit]]
        next_cursor = f"{page[-1]['created_at_num']}:{page[-1]['id']}" if len(rows) > limit else None
        return {"entries": page, "next_cursor": next_cursor, "day": day, "timezone": timezone_name}


def meaningful_recall_query(query: str) -> bool:
    compact = re.sub(r"[\W_]+", "", query.lower())
    return len(compact) >= 3 and compact not in {
        "继续",
        "接着",
        "然后呢",
        "接下来呢",
        "好的",
        "为什么",
        "第二个",
        "第二个呢",
        "再说说",
        "continue",
        "goon",
        "next",
        "whatnext",
        "yes",
        "ok",
        "thesecondone",
        "why",
        "tellmemore",
    }
