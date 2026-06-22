# Yumi HTTP API (core server)

HTTP integration guide for **any language**. Core implementation lives in the [`yumi/core/api/`](../yumi/core/api/) package.

## Basics

| Topic | Notes |
|--------|--------|
| Default local base URL | `http://127.0.0.1:8000` (clients may override with `YUMI_SERVER_URL`) |
| Interactive docs | After the core server starts: `/docs` (Swagger UI) or `/openapi.json` |
| CORS | The core defaults to localhost-only browser origins; widen explicitly with env vars if you need cross-origin browser access |

**Security:** these endpoints assume localhost or a trusted LAN. If you expose the server to the public internet, add authentication, TLS, and access controls yourself.

### Security and deployment (trust boundaries)

| Scenario | What to assume | Recommendations |
|----------|----------------|-----------------|
| **Core server on `127.0.0.1`** | Only local processes can reach the API | Default for development; do not forward this port to the public Internet without adding auth/TLS |
| **LAN binding** | Anyone on the same network may call local management routes unless you add controls | Use a firewall; prefer **Tailscale** or similar for remote access instead of raw port exposure |

The **core** HTTP API does not require a Bearer token by default: treat it as **trusted network** only.

### Browser CORS configuration

Yumi now uses **restricted browser defaults**:

- `YUMI_CORS_ORIGINS` controls which browser origins may call the **core** API.
- `YUMI_CORS_ALLOW_CREDENTIALS` controls whether browsers may send credentials to the **core** API.

Behavior:

- If unset, the core allows only localhost-style development origins.
- Browser credentials are **off by default**.
- If you set origins to `*`, Yumi forces browser credentials back off because wildcard origins and credentialed requests are incompatible in browsers.

Examples:

```bash
# Allow a custom browser client to call the core API on a trusted private network.
export YUMI_CORS_ORIGINS="https://dashboard.example.internal"
```

---

## Chat: `POST /chat`

- **Request Content-Type:** `application/json`
- **Response Content-Type:** `application/x-ndjson` (one JSON object per line)

### Request body

| Field | Type | Required | Default | Description |
|--------|------|----------|---------|-------------|
| `prompt` | string | yes | — | User message |
| `session_id` | string | no | `"default"` | Session id for context isolation |
| `think` | boolean | no | `false` | Enable “thinking” style output when supported by the model/provider |

### Response body (streaming NDJSON)

Each line is one JSON object and includes a `type` field. Common values:

| `type` | Meaning | Typical extra fields |
|--------|---------|----------------------|
| `text` | Model text tokens | `content` |
| `thought` | Reasoning / thought chain (when enabled) | `content` |
| `tool_status` | Tool execution status | `status` (e.g. `running` / `success` / `error`), `content` |
| `tool_confirmation` | Tool call waiting for user confirmation | `call_id`, `tool_name`, `full_tool_name`, `arguments` |
| `error` | Error message | `content` |

Clients should `json.loads` each line and branch on `type`.

### `curl` example

```bash
export YUMI_SERVER_URL="${YUMI_SERVER_URL:-http://127.0.0.1:8000}"

curl -sN -X POST "$YUMI_SERVER_URL/chat" \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Introduce yourself in one sentence.","session_id":"api-demo","think":false}'
```

`-N` disables buffering so streamed lines appear as they arrive.

### Working with `POST /tools/confirm`

When the stream emits `type: tool_confirmation`, the web UI calls the confirm endpoint; custom clients must call `POST /tools/confirm` with the user’s decision or the confirmation may time out and be denied. Request body fields are documented in OpenAPI and in `ToolConfirmationResponse` in the source.

---

## Other common HTTP routes (core)

All paths are relative to the core base URL (e.g. `http://127.0.0.1:8000`).

### Health

- `GET /health` — JSON with server status and runtime readiness details.

### Sessions and memory

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/clear` | Clear a session; query `session_id` (default `default`) |
| `GET` | `/memory/sessions` | List sessions; query `status` (default `active`) |
| `POST` | `/memory/sessions` | Create session; optional JSON `title` |
| `GET` | `/memory/sessions/{session_id}` | Get one session |
| `PUT` | `/memory/sessions/{session_id}` | Update session (title, pin, status, …) |
| `GET` | `/memory/messages` | Paginated messages; `session_id`, `limit`, `offset` |
| `GET` | `/memory/messages/{message_id}` | One message |
| `POST` | `/memory/messages` | Create message; JSON: `session_id`, `role`, `content` |
| `PUT` | `/memory/messages/{message_id}` | Update message |
| `DELETE` | `/memory/messages/{message_id}` | Delete message |
| `GET` | `/memory/search` | Semantic search; **required** query `query`; optional `session_id`, `limit` |

### Config and tools

| Method | Path | Description |
|--------|------|-------------|
| `GET` / `PUT` / `DELETE` | `/config/system-prompt` | Global system prompt; `PUT` body `{"system_prompt":"..."}` |
| `GET` / `PUT` | `/config/model` | Read/update model, memory, and Edge tool-routing settings; `PUT` may include `edge_tools_enable_dynamic_routing`, `edge_tools_retrieval_limit`, `openai_api_key`, `gemini_api_key`, `claude_api_key`, `deepseek_api_key`, `grok_api_key`, `openai_base_url`, `deepseek_base_url`, `grok_base_url` (non-empty key values are saved to `~/.yumi/config.json`; `GET` never returns raw keys, only `*_saved` / `*_effective` flags and saved base URLs; `embedding_provider` must be `openai`, `gemini`, `fastembed`, `ollama`, or `disabled`) |
| `GET` / `PUT` / `DELETE` | `/config/session-prompt/{session_id}` | Per-session system prompt override |
| `GET` / `PUT` | `/config/chat-debug` | Per-session chat NDJSON tracing: `GET` returns `enabled` and `trace_path`; `PUT` body `{"session_id":"...", "enabled": true|false}` starts/stops appending trace lines under `YUMI_DEBUG_DIR/chat_trace/`. Each turn logs `llm_provider_request` with the full provider `messages` and `tools` after prompt composition (system prompt, memory, tool results, multimodal parts). Optional `YUMI_CHAT_DEBUG_REDACT_IMAGE_DATA` shrinks logged base64 (see configuration docs). |
| `GET` / `PUT` | `/config/ui` | UI preferences (e.g. dark mode) |
| `GET` | `/tools` | List server and connected Edge tools |
| `POST` | `/tools/toggle` | Enable/disable tool: `{"tool_name":"...","disabled":true}` |
| `POST` | `/tools/set-confirmation` | Tool confirmation policy |
| `POST` | `/tools/confirm` | Respond to `tool_confirmation` stream events |
| Various | `/tools/...`, `/tools/edge/...` | Tool source and Edge file CRUD (see OpenAPI) |

### Error responses (structured `detail`)

Many endpoints return FastAPI’s `{"detail": ...}` body. For model configuration and related failures, `detail` is often an object with:

| Field | Meaning |
|-------|---------|
| `code` | Stable machine-readable identifier (e.g. `YUMI_MISSING_OPENAI_KEY`, `YUMI_OLLAMA_UNAVAILABLE`, `YUMI_UNKNOWN_PROVIDER`, `YUMI_PROVIDER_MODEL_APPLY_FAILED`) |
| `message` | Short user-facing explanation |
| `hint` | Optional remediation (env var, config path, etc.) |

Legacy string-only `detail` values still appear for older routes. Validation errors (`422`) may return `detail` as a list of field errors.

### Monitoring (topology and tool traces)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/monitor/topology` | Server label metadata, `local_tool_count`, and `edges[]` (`edge_name`, `online`, `tool_count`) |
| `GET` | `/monitor/traces` | Recent tool invocations; query `session_id` (optional), `limit` (1–500, default 100) |
| `GET` | `/monitor/traces/export` | NDJSON download of traces (optional `session_id`); same filter as list |

Traces may be mirrored to `~/.yumi/tool_traces.jsonl` on disk (append-only); the in-memory buffer is also bounded.

### Timer events (NDJSON stream)

- `GET /timer-events` — long-lived stream, `application/x-ndjson`, for timer pushes (includes `heartbeat`).

## Trying the API manually

Run `yumi --server` locally first, and complete `yumi --setup` (or set model-related environment variables). The **`POST /chat`** section above documents the NDJSON line protocol and includes a **curl** example. Interactive exploration: open `/docs` on the running server.

---

## Stability notes

Yumi is still in the **0.x** stage. For HTTP integrations, treat the documented routes in this file and the generated OpenAPI schema as the intended public contract. Internal Python modules and undocumented routes may change between releases.
