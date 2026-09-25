# Agent turn context and tool discovery

Each request retains an in-memory snapshot of its initial prompt, recalled facts,
related history and runtime notes. Completed tool spans are appended to that
snapshot and independently persisted. Reading the next model round does not
reconstruct the active task from the sliding history window. A memory redaction
invalidates an in-flight snapshot.

Tool results retain their call IDs through approval, execution, SQLite and replay.
Current turns reject missing, duplicate and unmatched IDs. Legacy results can be
recovered by a unique function name; ambiguous outcomes are explicitly unknown.
No positional pairing is performed.

## Tool visibility and discovery

Routing, discovery, forced additions and connected-device context share the scoped
catalog, including personal `disabled` and `ai_access=none` settings. Execution
rechecks policy after confirmation. Manual execution keeps its separate policy.

`YUMI_EDGE_TOOLS_ROUTING_MODE=on_demand` keeps discovery and catalog browsing
available alongside common core functions. A complete catalog that fits
`tool_schema_token_budget` is sent directly, including core functions. Otherwise,
if the common core set plus visible edge schemas fits, those edge functions
(including dynamic tools) are available immediately; relevant extra core functions
are recalled locally and admitted under the same budget. It does not depend on the
legacy numeric small-catalog threshold. Otherwise, the initial user request
recalls up to eight ranked matches, bounded by `edge_tools_retrieval_limit`, with
explicit same-device function references admitted as companions (one hop, at most
two per match). All additions must fit the schema budget. Legacy sticky/per-turn/
off modes and the OSS sticky default remain supported. Nexus uses on-demand mode.

Retrieval combines lexical and cached semantic ranks instead of replacing lexical
matches with vector results. Exact function/device names get priority. A small
offline Chinese/Japanese capability vocabulary helps common music, lighting,
reminder, weather, notes and file requests; it is not a universal translator.
Single CJK characters are not expanded as separate query terms: shared particles
in song titles should not match unrelated descriptions. Explicit function
references in a description (for example, `music_play` requiring a result from
`music_search`) preserve a tool chain in both directions without loading every
sibling. `create/add_RESOURCE` also recalls visible `update/get_RESOURCE`
siblings for follow-up corrections. Only same-device functions qualify.

`discover_app_tools` searches visible core and edge functions, starting with six
matches plus bounded companions. Its response distinguishes no match, no visible
tools and schema-budget exclusion, and separately reports degraded retrieval.
Suitable visible/activated functions should be used directly, even if semantic
ranking was degraded. Degradation alone is not a reason for another search or
catalog browse. Ordinary answers that need no external action need no discovery.
An empty search is **not evidence that a capability is absent**. The prompt asks
the model to try at most two distinct searches and then inspect relevant devices;
it must describe an incomplete inspection honestly rather than claim no tool
exists. These instructions guide the model; they are not a hard semantic check of
its final prose.

`browse_app_tools` is the deterministic fallback, independent of embeddings:

1. Call with `device=""` to page through visible devices and capability previews.
2. Pass a returned `device_id` (or an exact unique name) to list and activate a page
   of functions. Follow `next_offset`; default page size is six, maximum twenty.
3. Pass `catalog_revision` on subsequent pages. If visibility or schemas changed,
   restart at offset zero. Unknown and unauthorized devices share the same result.
4. Only `activated_tool_names` is eligible for the next model request. Metadata for
   a function that exceeds the schema budget remains browsable. Retry a smaller
   page; a single oversized schema needs an operator budget adjustment.

Browsing executes no business functions. Loading metadata does not override tool
confirmation, personal policy or execution-time access checks. Online status is
reported separately from discoverability. Runtime device previews are bounded to
eight devices and are explicitly incomplete; the paginated catalog stays reachable.

Tool metadata vectors are cached across restarts by provider endpoint, model and
content hash. Startup queues core metadata; edge registration queues device
metadata. A bounded-concurrency worker coalesces updates without dropping other
devices during registration bursts. Only metadata vectors are persisted, never
request text or query vectors. On-demand retrieval makes at most one query
embedding call and never builds missing metadata vectors on the chat path.
Missing or failed vectors produce explicit degraded retrieval with lexical and
catalog fallbacks. A failed warm-up can leave an incomplete index until a later
registration or restart; browsing remains available.

Semantic work (including metadata cache reads) has a 750 ms wait budget during
initial on-demand routing, or 1 second during explicit discovery. Routing runs
alongside independent autorun context preparation rather than after it. A cold index
does not issue a query embedding when there are no indexed documents to compare.
At most four semantic jobs run concurrently with no unbounded queue. A synchronous
provider call can outlive the caller's deadline; it retains its worker slot until
completion, and new requests use lexical retrieval while the pool is saturated.
Worker contexts preserve account and per-turn embedding-cache isolation. These
limits bound the semantic routing wait, not LLM generation, independent memory
retrieval, device execution, or total user-visible response time.

On-demand routing also carries up to 24 discovered or successfully used function
names per account/session for 30 minutes after discovery/use. It resolves those
names against the current scoped catalog on every turn; permissions and schemas
are never cached. Removed/disabled functions are discarded, session reset clears
the names, and storage is bounded to 4,000 sessions. Current request matches have
budget priority over carried names. Equal membership serializes in stable name
order, and an implicit follow-up can use an already discovered function without
another model discovery round. This caches neither tool results nor authorization
to execute; existing confirmation and execution checks still apply.

Routing traces record `retrieval_mode`, `retrieval_degraded`,
`retrieval_degraded_reason`, `reused_tool_count` and admitted tool names.
Discovery results also record `retrieval_elapsed_ms`; reason values distinguish
`timeout`, `busy`, `index_incomplete` and `unavailable`. Discovery/browse results
record activation and budget exclusions. These
separate “registered”, “visible”, “retrieved” and “sent to the next model call”.

Regression fixtures in `tests/fixtures/room_music_tools.json` preserve the twelve
RoomMusicMacMini tool descriptions used for the reported failure. Tests cover
mixed Chinese/Japanese requests and a misspelled artist, 30/300 unrelated tools,
provider failure, cold indexes, paging, schema budgets, policy changes and actual
chat-loop activation. They run without a real model or music playback.

Run `.venv/bin/python -m tools.benchmarks.tool_discovery` for an offline latency
and search/play recall benchmark with 12, 312 and 1,012 edge functions, cold/warm
indexes and a simulated slow provider. It does not measure live cloud response
time. Latency regressions cover a blocked provider, worker saturation, account
context, follow-up reuse, expiration and permission/schema changes.

## Budgets and termination

Model configuration:

| Setting | Default | Purpose |
| --- | ---: | --- |
| `chat_input_token_budget` | 32,000 | Estimated messages plus function schemas |
| `chat_max_output_tokens` | 4,096 | Provider generation limit |
| `tool_schema_token_budget` | 6,000 | Function schemas; latest discoveries take priority |

Input estimates are conservative, not a model-specific tokenizer. The input and
output limits must be configured within the chosen model's context capacity.
Old completed turns are removed as units before shortening oversized tool results.
The active user task, tool pair identities and required rules/recall remain. If
those still exceed the budget, the request fails clearly before model execution.

After ten tool rounds the model receives one no-tools closing round. A tool
timeout is recorded as an unknown outcome, because local threads and remote
operations may still complete. The turn closes without automatically retrying.
This is not a claim of transactional exactly-once execution across edge systems.

## Reasoning and accounting

DeepSeek receives an explicit thinking enabled/disabled setting. Thinking tool
requests replay available historical reasoning, including final assistant turns;
legacy messages have an empty reasoning field. Other providers retain their own
capabilities. Traces separate the requested adapter setting from observed reasoning
and include per-message and schema input estimates.

The usage ledger has additive `usage_kind` and `estimated` columns. Chat, summary,
embedding and tool search consumption is associated with the account and originating
turn when available. Tool metadata indexing is system-owned. API-reported embedding
usage is preferred; estimates are marked. Monthly totals include auxiliary work,
while request counts count chat turns. Earlier usage is not retroactively inferred.
