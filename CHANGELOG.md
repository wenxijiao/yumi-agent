# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- **Internal restructure (`kumi/core/`): platform / features split.** Modules
  were reorganized into `kumi/core/platform/` (cross-cutting infra),
  `kumi/core/features/<feature>/` (self-contained capabilities), and a slim
  `kumi/core/api/` HTTP composition root. Deprecated re-export **shims remain at
  every old import path**, so existing code keeps working unchanged. New code
  should use the new paths. See `docs/MIGRATION_PLATFORM_FEATURES.md` for the
  full old→new map. Downstream packages (`kumi-enterprise`, `kumi-nexus`) still
  import several old paths via the shims and should migrate before the shims are
  removed in a future release.

### Security

- `~/.kumi/config.json` is now written atomically with `0o600` and the parent
  directory chmod'd to `0o700` so cloud API keys, Telegram/LINE tokens, the
  Picovoice access key, and `lan_secret` aren't readable by other local users.
- Built-in `read_file` / `list_files` tools default to **require_confirmation**
  (opt out via `local_tools_always_allow`) and reject paths inside `~/.ssh`,
  `~/.aws`, `~/.gnupg`, `~/.kumi`, plus `*.pem` / `*.key` / `id_rsa*` /
  `authorized_keys` / `credentials` files. Mitigates prompt-injection from
  uploaded data trying to exfiltrate local secrets.
- `KUMI_CORS_ORIGINS=*` combined with `_ALLOW_CREDENTIALS=true` now raises at
  startup rather than silently demoting credentials.
- Provider exception text on `PUT /config/model` failure is logged
  server-side; the HTTP response now carries a generic hint so SDK error
  bodies (which can include URLs / partial credentials) don't leak.

### Added

- **Microphone wake-word voice mode**: `kumi --server --voice` (composable
  with `--telegram`) attaches a Picovoice + faster-whisper loop. New optional
  extras: `[voice]` (sounddevice + webrtcvad + pvporcupine) and `[stt]`
  (faster-whisper). New config keys: `voice_owner_id`,
  `voice_porcupine_access_key`, `voice_porcupine_keyword_path`,
  `voice_porcupine_sensitivity`, `voice_input_device`, `voice_silence_ms`,
  `voice_max_utterance_ms`, `voice_vad_aggressiveness`, `voice_wake_word`.
  Environment: `KUMI_VOICE_ENABLED`, `KUMI_VOICE_OWNER_ID`, `PV_ACCESS_KEY`.
- **Proactive messaging modes**: `proactive_mode` (`off` | `smart` | `scheduled`) with `proactive_schedule_times`, `proactive_schedule_interval_minutes`, and `proactive_schedule_require_idle`. Legacy JSON without `proactive_mode` derives mode from `proactive_enabled`; `proactive_enabled` is still saved and synced from mode on load. Environment: `KUMI_PROACTIVE_MODE`, `KUMI_PROACTIVE_SCHEDULE_TIMES`, `KUMI_PROACTIVE_SCHEDULE_INTERVAL_MINUTES`, `KUMI_PROACTIVE_SCHEDULE_REQUIRE_IDLE`.
- **`local_timezone`** in `config.json`: IANA zone for user-facing wall time (chat clock, proactive context, proactive quiet hours, proactive daily limit calendar). Legacy JSON key `proactive_quiet_hours_timezone` is still read on load; prefer **`KUMI_LOCAL_TIMEZONE`** over `KUMI_PROACTIVE_QUIET_HOURS_TIMEZONE` at runtime.
- Proactive messaging: `proactive_check_interval_jitter_ratio`, `proactive_unreplied_escalation_jitter_ratio`, and `proactive_check_in_probability` for less rigid scheduling; matching `KUMI_PROACTIVE_*` environment variables.

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

## [0.2.0] - 2026-04-20

### Changed

- **Repository split**: this `kumi-agent` package is now the open-source single-user / LAN core. Multi-tenant, relay, billing, admin, and remote-pairing features moved to the closed-source `kumi-enterprise` package, which extends the core via the new `kumi.core.plugins` port system (`IdentityProvider`, `QuotaPolicy`, `BotPool`, `MemoryFactory`, `SessionScope`, `EdgeScope`, `AuditSink`, `BillingHook`, `RouteExtender`, `MiddlewareExtender`).
- The OSS HTTP API now boots with `single_user` defaults: requests resolve to the local identity (`_local`), there is no Bearer auth requirement, and there are no quotas, billing, or per-tenant scoping.
- CLI surface trimmed to `--server`, `--ui`, `--chat`, `--telegram`, `--line`, `--edge`, `--demo`, `--setup`, `--cleanup`, `--cleanup-memory`. The provisioning / migration / relay flags (`--admin`, `--tenant-create`, `--user-add`, `--user-token`, `--user-token-revoke`, `--user-set-scope`, `--rotate-user-keys`, `--migrate-tenancy`, `--db-upgrade`, `--db-current`, `--db-stamp`, `--memory-prune`, `--relay`) ship in the enterprise CLI.
- `kumi.core.connection` is now LAN-only (`mode="direct"`); relay profile bootstrap, persistence, and the `mode="relay"` connection variant moved to enterprise.
- `kumi.core.auth` now exposes only `KumiLanCode` and helpers; `KumiCredential` (signed Bearer tokens) and refresh-token flows moved to enterprise.
- LINE bridge (`kumi.line.handlers`, `kumi.line.bridge`) is now stateless single-user; `/link`, `/usage`, per-LINE-user token persistence, and per-user model overrides moved to enterprise.
- Removed dependency pins on `slowapi` and `alembic` (multi-tenant rate-limit + DB migrations live in enterprise). The optional `postgres` extra is no longer published from OSS.

### Internal

- New `kumi/core/plugins/` package with `Identity`, `LOCAL_IDENTITY`, `Protocol` ports, single-user defaults, a runtime registry, and `entry_points`-based plugin discovery (`kumi.plugins` group).

## [0.1.x]

### Changed

- Internal Python layout: split user config into `kumi.core.config` package, prompts into `kumi.core.prompts`, memory helpers (`constants`, `tool_replay`, `embedding_state`), CLI as `kumi.cli` package with `terminal_chat`, streaming/error helpers, and renamed `kumi/tools/bootstrap.py` (was `setup.py`) for tool registration. User-facing HTTP routes, CLI commands, and SDKs are unchanged.
- Restricted default browser CORS for the core API and Relay to localhost-style origins, with explicit env vars for widening access.
- Refactored the core HTTP server into the `kumi.core.api` package (`routes`, `state`, `chat`, `edge`, `timers`, `peers`, `schemas`) to reduce module-level global state and improve testability.
- Expanded CI-safe tests: chat streaming, credential validation, Relay bootstrap/auth, CLI environment selection, edge WebSocket handshake, health endpoint, and cross-SDK contract tests (Python/Go/TypeScript/Java schema shape verification).
- Clarified public API stability, deployment hardening, and package metadata for external users.
- Replaced deprecated LanceDB `table_names()` checks with `list_tables()`-first compatibility helpers in memory storage to remove deprecation warnings on current releases.
- Added `build` to the development extras and documented a local pre-release smoke check for maintainers.
- Added `kumi --cleanup-memory` to clear persisted memory without deleting saved config, prompts, profiles, or connection codes.

[0.2.0]: https://github.com/wenxijiao/kumi-agent/releases/tag/v0.2.0

## [0.1.0] - 2026-04-11

### Added

- Initial documented release baseline: local-first agent, CLI (`kumi`), FastAPI server, Reflex web UI, multi-language edge SDKs, HTTP API and docs.

[0.1.0]: https://github.com/wenxijiao/kumi-agent/releases/tag/v0.1.0
