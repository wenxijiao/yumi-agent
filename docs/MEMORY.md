# Memory and chat context

This document describes what Yumi persists and how it reaches the model.

## Internal layout

The core implementation is split into a façade plus per-aggregate repositories so storage backends can be swapped without rewriting the public surface:

```
yumi/core/features/memory/
├── memory.py              # Memory façade (public class)
├── backend.py             # LanceDBBackend: connection, table helpers, time/SQL primitives
├── embedding_runner.py    # EmbeddingProcessor: dim migration + background re-embed
└── repos/
    ├── messages.py        # MessageRepository       — chat_history
    ├── sessions.py        # SessionRepository       — chat_sessions
    ├── long_term.py       # LongTermMemoryRepository — long_term_memories
    ├── observations.py    # ToolObservationRepository — tool_observations
    └── summaries.py       # SessionSummaryRepository — session_summaries
```

Public methods on `Memory` (e.g. `add_message`, `create_session`, `list_long_term_memories`) stay thin: reads delegate to the appropriate repository, while canonical writes commit to SQLite first and then best-effort update the matching LanceDB repository. The `Memory` constructor signature has not changed; existing call sites (`YumiBot.session_memory(...)`, plugin memory factories, tests that pass `storage_dir=tmpdir`) keep working unchanged.

## Storage

- Chat messages and sessions (per `session_id`) are stored canonically in **SQLite** at `~/.yumi/yumi.db` — the single source of truth (see `db_path_for_memory_storage()`). **LanceDB** is a *derived, rebuildable* vector index under the user memory directory (see `migrate_legacy_memory_dir()`), holding the `chat_history` and `chat_sessions` tables: canonical writes commit to SQLite first and then best-effort update the index, which can be rebuilt from SQLite at any time (e.g. on an embedding-model change).
- `YumiBot` keeps an in-memory LRU of at most **64** `Memory` instances; evicting one **does not delete** persisted data. The next request for that session reloads from disk.
- Structured memory is stored separately from raw chat rows:
  - `session_summaries` keeps a rolling summary per session.
  - `long_term_memories` stores durable facts, preferences, decisions, task state, and summaries.
  - `tool_observations` stores compact tool-call outcomes so later turns can reuse what tools already found.

To delete persisted memory without wiping the rest of Yumi config, run:

```bash
yumi --cleanup-memory
```

This clears the canonical memory tables in `~/.yumi/yumi.db`, removes the derived index directory (`~/.yumi/memory/`), and removes any legacy on-repo memory store if it still exists.

## What is persisted

| Data | Persisted |
|------|-----------|
| User messages | Yes |
| Final assistant **text** replies (no tool call in that step) | Yes |
| Assistant **tool_calls** + following **tool** results for each tool round | Yes (encoded rows; replayed in `get_context`) |
| Ephemeral-only context for the **current** multi-tool loop | Only the parts above are written; the in-memory `ephemeral_messages` list itself is not stored as a blob |
| High-signal preferences / facts / decisions | Yes, selectively extracted into `long_term_memories` |
| Tool results | Yes, replayed in `chat_history` and summarized into `tool_observations` |

## Retrieval (`Memory.get_context`)

`Memory.get_context` now delegates to a `ContextBuilder` instead of assembling one flat transcript directly.

1. One **system** message: global or per-session prompt (`get_system_prompt` / `get_session_prompt`).
2. Optional structured memory block: hybrid retrieval over `long_term_memories` and `tool_observations`.
3. Optional current-session summary from `session_summaries`.
4. Optional **cross-session** block (`memory_max_related_messages` > 0): substring or vector search over raw chat messages; if the query embedding is **degenerate** (e.g. all zeros), search falls back to **substring** match to avoid meaningless ANN results.
5. Recent in-session rows (up to `memory_max_recent_messages`), including replayed **assistant+tool_calls** and **tool** rows when present.

Structured retrieval ranks candidates with semantic score when embeddings are available, keyword overlap, recency, importance, and memory-type boosts. If embeddings are unavailable, keyword and recency signals keep retrieval deterministic.

## Write policy

Raw chat history remains append-only for UI, audit, and provider replay. Long-term memory is selective:

- Explicit user preferences, project facts, and decisions are extracted by conservative rules.
- Tool results are compacted into tool observations with tool name, arguments summary, result summary, success flag, and importance.
- Low-signal turns such as acknowledgements are not promoted to long-term memory.
- A future LLM-based extractor can be added behind the same writer boundary without changing the public `Memory` API.

## Chat request extras (system message)

Configurable in `~/.yumi/config.json` or via `GET`/`PUT /config/model`:

- `chat_append_current_time` — append `[Current Time] ...` to system (default: `true`).
- `chat_append_tool_use_instruction` — append the English tool-use policy when tools are enabled (default: `true`).

Environment overrides (optional): `YUMI_CHAT_APPEND_CURRENT_TIME`, `YUMI_CHAT_APPEND_TOOL_INSTRUCTION` — set to `0`, `false`, or `no` to disable.
