# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.0.1] - Unreleased

### Added

- **Brand-new web UI** — a custom React + Vite + TypeScript + Tailwind
  single-page app (`yumi/ui/frontend/`) replacing the old Reflex UI. It ships
  pre-built as static assets served by the core server under `/app`, so end
  users need **no Node and no extra install** (`yumi --ui` just opens the
  browser). Pages: Chat (streaming, tool-call cards, tool-confirmation,
  file upload, mic input + spoken replies, sessions with pin/rename/search),
  Tools, a Stats dashboard, tabbed Settings, Schedules, Memory search, a
  first-run setup wizard, and a ⌘K command palette.
- **Persistent token-usage tracking** — each assistant turn's prompt/completion
  tokens are recorded to SQLite (`token_usage` table) and survive restarts.
- **`GET /stats`** — aggregated tool, token, session, and tool-call metrics for
  the dashboard.
- **`POST /tts/synthesize`** — text-to-speech for in-browser spoken replies
  (reuses the configured TTS provider).

### Changed

- `pip install yumi-agent` now includes local FastEmbed, Whisper STT,
  microphone wake-word dependencies, DashScope cloud STT/TTS, and the pre-built
  web UI. Only local-GPU Qwen TTS (`[tts-local]`) remains an optional extra;
  model weights and embedding assets are still downloaded on demand.
- `yumi --ui` no longer requires Node.js or a Reflex dev server; it verifies the
  core server is running and opens the browser at its `/app` page.
- Default conversation context raised to 30 recent + 15 cross-session related
  messages.
- Migrated PDF ingestion from the end-of-life `PyPDF2` to `pypdf`; added explicit
  `pydantic` and `av` (PyAV) dependencies.
- Windows `system` TTS now uses the built-in SAPI voice through PowerShell,
  matching the zero-dependency spoken-reply path already available on macOS and
  Linux.

### Fixed

- Core (agent loop + memory storage):
  - **SQLite is now the authoritative write** for every message; the LanceDB
    vector index is a derived, best-effort write that is rebuilt from SQLite when
    needed — so an index hiccup can no longer lose a canonical message (the write
    order was previously inverted).
  - Added `Memory.rebuild_index_from_sqlite()` to drop and regenerate the LanceDB
    query index from SQLite (e.g. after changing the embedding model, or to repair
    drift).
  - Removed the never-consumed `embedding_jobs` / `vector_index_records` queue
    (it grew unbounded and was dead scaffolding; embeddings are generated inline
    and the index is rebuilt from SQLite on demand).
  - Chat: a malformed-tool-call retry no longer re-sends and re-persists the
    user's message on each attempt.
- Pre-release hardening (web UI + voice):
  - Cloud STT (Gemini/DashScope/Grok) now transcodes browser WebM/MP4 recordings
    to WAV via PyAV, and the mic upload filename matches the real container
    (Safari/iOS), so microphone input works across providers and browsers.
  - The mic button is disabled with a hint when STT is off; spoken-reply (TTS)
    failures now surface a toast instead of failing silently; "Test voice" saves
    the current selection first and no longer leaks audio URLs.
  - Added a DashScope/Qwen API-key field to Settings → Voice (previously
    unconfigurable from the browser).
  - Chat: collapsing the sidebar can no longer strand you with no controls; a
    failed message reload no longer wipes the transcript; the active session
    persists across refreshes.
  - The Settings "Configuration Storage" note now shows the correct path
    (`~/.yumi/config.json`), command (`yumi --config`), and an accurate
    (non-"encrypted") description of how keys are stored.
  - `/stats` runs off the event loop and aggregates the full trace buffer (not a
    500-row slice); per-turn token persistence no longer reloads the full config.
  - The UI self-hosts the Inter font (no external CDN) and code-splits routes for
    a lighter initial load; a server-unreachable banner and a discoverable setup
    wizard were added.

### Removed

- The Reflex web UI and the `[ui]` optional dependency extra.

## Development Notes - 2026-06-28

### Added

- **Cloud speech-to-text providers.** Alongside local Whisper, `stt_provider` now
  accepts three no-download cloud backends that reuse your existing provider API
  keys: `openai` (OpenAI transcription — `gpt-4o-mini-transcribe`,
  `gpt-4o-transcribe`, `whisper-1`; honors `openai_base_url` for OpenAI-compatible
  proxy / Azure endpoints), `gemini` (Gemini 2.5 models transcribe inline audio
  via `gemini_api_key`), and `dashscope` (Qwen3-ASR `qwen3-asr-flash` via the
  shared DashScope key). `yumi --setup` configures them; `YUMI_STT_PROVIDER`
  accepts the new values.
- **OpenAI text-to-speech.** `tts_provider = openai` speaks replies through the
  OpenAI speech API (`gpt-4o-mini-tts` / `tts-1` / `tts-1-hd`) using
  `openai_api_key`, joining `system` / `dashscope` / `qwen`. Output is WAV so it
  plays through the same zero-config local backends (`winsound` / `aplay` /
  `afplay`) as the other providers.
- **Redesigned setup wizard.** `yumi --setup` is now a navigable,
  alternate-screen step flow (AI model → memory → voice input → spoken replies →
  messaging) with back/next navigation, a calm progress rail, an immediate test
  line per feature, and on-demand extra installs. Non-interactive / piped
  invocations degrade gracefully and cancel cleanly on closed stdin.
- **Missing-credential preflight.** Launching the server or a bridge surfaces any
  configured cloud feature whose API key is absent — fatally for the chat model,
  as a non-blocking warning for memory / voice — via `missing_credentials()`.
- **TTS environment overrides**: `YUMI_TTS_PROVIDER`, `YUMI_TTS_VOICE`,
  `YUMI_TTS_MODEL`, `YUMI_TTS_LANGUAGE`, mirroring the existing `YUMI_STT_*`.

### Changed

- `rich` is now a base dependency (used for the redesigned wizard rendering).

## Development Notes - 2026-06-19

### Changed

- **Internal restructure (`yumi/core/`): platform / features split.** Modules
  were reorganized into `yumi/core/platform/` (cross-cutting infra),
  `yumi/core/features/<feature>/` (self-contained capabilities), and a slim
  `yumi/core/api/` HTTP composition root, with a strict dependency rule
  (features → platform, never the reverse) enforced by tests. The old import
  paths were retired — no compatibility shims remain, so only the new paths are
  importable. See `docs/MIGRATION_PLATFORM_FEATURES.md` for the full old→new map.
- **Batteries-included base install.** `pip install yumi-agent` now bundles the
  LLM providers (OpenAI / Gemini / Claude, incl. DeepSeek), the Telegram +
  Discord bridges, and file ingestion, so they work out of the box. Only heavy /
  system-dependent features remain as extras (`[ui]`, `[stt]`, `[voice]`,
  `[tts]`, `[tts-local]`), and `yumi --setup` offers to install those on demand
  when you enable the feature. The now-redundant
  `[openai]`/`[gemini]`/`[claude]`/`[deepseek]`/`[providers]`/`[telegram]`/
  `[discord]`/`[line]`/`[files]` extras were removed (folded into the base).

### Security

- `~/.yumi/config.json` is now written atomically with `0o600` and the parent
  directory chmod'd to `0o700` so cloud API keys, Telegram/LINE tokens, the
  Picovoice access key, and `lan_secret` aren't readable by other local users.
- Built-in `read_file` / `list_files` tools default to **require_confirmation**
  (opt out via `local_tools_always_allow`) and reject paths inside `~/.ssh`,
  `~/.aws`, `~/.gnupg`, `~/.yumi`, plus `*.pem` / `*.key` / `id_rsa*` /
  `authorized_keys` / `credentials` files. Mitigates prompt-injection from
  uploaded data trying to exfiltrate local secrets.
- `YUMI_CORS_ORIGINS=*` combined with `_ALLOW_CREDENTIALS=true` now raises at
  startup rather than silently demoting credentials.
- Provider exception text on `PUT /config/model` failure is logged
  server-side; the HTTP response now carries a generic hint so SDK error
  bodies (which can include URLs / partial credentials) don't leak.

### Added

- **Discord bridge**: chat with Yumi from a Discord bot — `yumi --server --discord`
  or `yumi --discord` (gateway connection, no public URL needed). Tool confirmations
  are Allow / Deny / Always-allow buttons; allowlist via `DISCORD_ALLOWED_USER_IDS`.
  Ships in the base install. Joins the existing Telegram and LINE bridges.
- **SDK robustness (`YumiAgent`)**: logs via the `yumi.sdk` logger instead of
  `print`; exposes `is_connected` and an optional `on_error` callback; resolves the
  connection inside the reconnect loop so a transient connection-bootstrap failure
  at startup no longer permanently kills the client; `register()` now raises on a
  duplicate or empty tool name; and `yumi.run()` configures the default agent via
  the public `run_in_background(...)` instead of touching private attributes.
- **Microphone wake-word voice mode**: `yumi --server --voice` (composable
  with `--telegram`) attaches a Picovoice + faster-whisper loop. New optional
  extras: `[voice]` (sounddevice + webrtcvad + pvporcupine) and `[stt]`
  (faster-whisper). New config keys: `voice_owner_id`,
  `voice_porcupine_access_key`, `voice_porcupine_keyword_path`,
  `voice_porcupine_sensitivity`, `voice_input_device`, `voice_silence_ms`,
  `voice_max_utterance_ms`, `voice_vad_aggressiveness`, `voice_wake_word`.
  Environment: `YUMI_VOICE_ENABLED`, `YUMI_VOICE_OWNER_ID`, `PV_ACCESS_KEY`.
- **Spoken replies (text-to-speech)**: Yumi can talk back. Three backends behind
  one provider choice — `system` (macOS `say` / Linux `espeak`, zero-dependency
  default), `dashscope` (Qwen3-TTS via the Alibaba Cloud DashScope API), and
  `qwen` (Qwen3-TTS run locally on a GPU). `yumi --setup` configures it (with an
  immediate test line); `yumi --speak "..."` is a smoke test; `--server --voice`
  speaks replies automatically; Telegram `/voice on|off` and Discord
  `!voice on|off` switch a chat between text and audio replies. New config keys
  `tts_provider`, `tts_voice`, `tts_model`, `tts_api_key`, `tts_language`; new
  extras `[tts]` (DashScope) and `[tts-local]` (local qwen). Environment:
  `DASHSCOPE_API_KEY`, `DASHSCOPE_BASE_URL`.
- **Proactive messaging modes**: `proactive_mode` (`off` | `smart` | `scheduled`) with `proactive_schedule_times`, `proactive_schedule_interval_minutes`, and `proactive_schedule_require_idle`. Legacy JSON without `proactive_mode` derives mode from `proactive_enabled`; `proactive_enabled` is still saved and synced from mode on load. Environment: `YUMI_PROACTIVE_MODE`, `YUMI_PROACTIVE_SCHEDULE_TIMES`, `YUMI_PROACTIVE_SCHEDULE_INTERVAL_MINUTES`, `YUMI_PROACTIVE_SCHEDULE_REQUIRE_IDLE`.
- **`local_timezone`** in `config.json`: IANA zone for user-facing wall time (chat clock, proactive context, proactive quiet hours, proactive daily limit calendar). Legacy JSON key `proactive_quiet_hours_timezone` is still read on load; prefer **`YUMI_LOCAL_TIMEZONE`** over `YUMI_PROACTIVE_QUIET_HOURS_TIMEZONE` at runtime.
- Proactive messaging: `proactive_check_interval_jitter_ratio`, `proactive_unreplied_escalation_jitter_ratio`, and `proactive_check_in_probability` for less rigid scheduling; matching `YUMI_PROACTIVE_*` environment variables.

### Fixed

- Chat **`[Current Time]`** and proactive context clocks honor **`local_timezone`** (IANA) instead of showing raw UTC when the server runs in UTC (e.g. Docker). When unset, they use the host OS local timezone.
- LINE webhook handler now ACKs 200 within LINE's ~1s retry window: signature
  verification stays in the request path, but chat-turn execution runs in a
  background task. Eliminates duplicate user messages under load.
- `<thinking>` / `<redacted_thinking>` parser holds back trailing `<` so a tag
  split across stream chunks is no longer leaked as visible text.
- Memory `list()` (observations + long_term) now pushes the `session_id`
  filter into the `WHERE` clause before applying `LIMIT`; busy multi-session
  DBs no longer silently drop matching rows.
- `LanceDBBackend.format_timestamp` now produces UTC so it round-trips with
  `parse_timestamp_num` (which has always interpreted the string as UTC).
- OpenAI streaming tool-call delta with `index=None` (older Azure / some
  vLLM builds) no longer crashes the chunk collector.
- Proactive scheduler releases the session lock before sending so a real
  user message isn't blocked behind LLM generation + inter-message delays;
  `record_sent` uses the actual send-start time, not the pre-LLM time.
- Voice loop no longer leaks the Porcupine native handle when audio source
  init fails; lifespan shutdown stops the source so the blocking executor
  read returns immediately instead of leaving a zombie thread.
- Whisper provider lazy `_load_model` is now lock-guarded so two concurrent
  first transcriptions don't both download/load the model.

## Development Notes - 2026-04-20

### Changed

- **Repository split**: this `yumi-agent` package is now the open-source single-user / LAN core. Higher-layer identity, policy, billing, and remote-pairing features live outside L1 and extend the core via the `yumi.core.platform.plugins` port system (`IdentityProvider`, `QuotaPolicy`, `BotPool`, `MemoryFactory`, `SessionScope`, `EdgeScope`, `AuditSink`, `BillingHook`, `RouteExtender`, `MiddlewareExtender`).
- The OSS HTTP API now boots with `single_user` defaults: requests resolve to the local identity (`_local`), there is no Bearer auth requirement, and there are no quotas, billing, or account scoping.
- CLI surface trimmed to `--server`, `--ui`, `--chat`, `--telegram`, `--line`, `--edge`, `--demo`, `--setup`, `--cleanup`, `--cleanup-memory`. Provisioning, migration, and public remote-access commands belong to higher layers.
- `yumi.core.platform.security.connection` is now LAN-only (`mode="direct"`); remote profile bootstrap, persistence, and alternate connection variants moved out of L1.
- `yumi.core.platform.security.auth` now exposes only `YumiLanCode` and helpers; signed Bearer tokens and refresh-token flows moved out of L1.
- LINE bridge (`yumi.line.handlers`, `yumi.line.bridge`) is now stateless single-user; account-linking and per-user overrides moved out of L1.
- Removed dependency pins on `slowapi` and `alembic` (rate-limit + DB migrations live outside L1). The optional `postgres` extra is no longer published from OSS.

### Internal

- New `yumi/core/platform/plugins/` package with `Identity`, `LOCAL_IDENTITY`, `Protocol` ports, single-user defaults, a runtime registry, and `entry_points`-based plugin discovery (`yumi.plugins` group).

## Early Development Notes

### Changed

- Internal Python layout: split user config into `yumi.core.features.config` package, prompts into `yumi.core.features.prompts`, memory helpers (`constants`, `tool_replay`, `embedding_state`), CLI as `yumi.cli` package with `terminal_chat`, streaming/error helpers, and renamed `yumi/tools/bootstrap.py` (was `setup.py`) for tool registration. User-facing HTTP routes, CLI commands, and SDKs are unchanged.
- Restricted default browser CORS for the core API to localhost-style origins, with explicit env vars for widening access.
- Refactored the core HTTP server into the `yumi.core.api` composition root, with shared HTTP infrastructure in `yumi.core.platform.http` and per-feature routers under `yumi.core.features.*`, to reduce module-level global state and improve testability.
- Expanded CI-safe tests: chat streaming, credential validation, CLI environment selection, edge WebSocket handshake, health endpoint, and cross-SDK contract tests (Python/Go/TypeScript/Java schema shape verification).
- Clarified public API stability, deployment hardening, and package metadata for external users.
- Replaced deprecated LanceDB `table_names()` checks with `list_tables()`-first compatibility helpers in memory storage to remove deprecation warnings on current releases.
- Added `build` to the development extras and documented a local pre-release smoke check for maintainers.
- Added `yumi --cleanup-memory` to clear persisted memory without deleting saved config, prompts, profiles, or connection codes.

## Initial Development Baseline - 2026-04-11

### Added

- Initial documented release baseline: local-first agent, CLI (`yumi`), FastAPI server, Reflex web UI, multi-language edge SDKs, HTTP API and docs.
