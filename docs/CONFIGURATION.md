# Configuration

Yumi's main persistent settings live in one file: `~/.yumi/config.json`.

To create or refresh that file with every known key and its default value:

```bash
yumi --config
```

Edit that JSON file for normal persistent configuration. Environment variables are still supported and always override the file at runtime, which is useful for secrets, Docker, CI, and system services.

## Config File Reference

`config.json` is standard JSON, so it cannot contain comments. Run `yumi --config` whenever you want a complete file with every currently supported key.

Model and provider fields:

- `chat_provider`: Chat model provider. Common values: `ollama`, `openai`, `gemini`, `claude`, `deepseek`, `grok`. Default: `ollama`.
- `chat_model`: Chat model name. `null` means Yumi will use provider defaults/setup.
- `embedding_provider`: Embedding provider. Default: `ollama`. `openai`, `gemini`, `fastembed`, and `ollama` can embed (`claude` / `deepseek` / `grok` have no embedding API); choose one of those for cross-session memory vectors. `fastembed` is the setup wizard's no-Ollama local option and downloads its embedding model from the CLI when selected.
- `embedding_model`: Embedding model name. `null` means provider default/setup.
- `embedding_dim`: Optional embedding vector dimension override. Usually leave `null`.
- `openai_api_key`, `openai_base_url`, `gemini_api_key`, `claude_api_key`, `deepseek_api_key`, `deepseek_base_url`, `grok_api_key`, `grok_base_url`: Saved provider credentials/base URL. Environment variables override these.

Prompt and session fields:

- `system_prompt`: Global system prompt override. `null` uses Yumi's default prompt.
- `session_prompts`: Per-session prompt overrides, keyed by session id such as `tg_123`.
- `chat_append_current_time`: Append current time to normal chat system context. Default: `true`. The timestamp uses `local_timezone` when set (IANA), otherwise the **host** system local timezone—so Docker/servers on UTC still show your city time when you set e.g. `Pacific/Auckland` in `local_timezone`.
- `chat_append_tool_use_instruction`: Append Yumi tool-use guidance when tools are available. Default: `true`.
- `local_timezone`: IANA timezone for **your** local wall clock (e.g. `Pacific/Auckland`). Used for: `[Current Time]` in chat (when `chat_append_current_time` is on), proactive outbound context clock, `proactive_quiet_hours` boundaries, and the calendar day for `proactive_daily_limit`. Unset or `null`: proactive quiet hours and daily limit use **UTC**; chat `[Current Time]` falls back to the host OS timezone. **Legacy:** the old key `proactive_quiet_hours_timezone` is still read from JSON on load and mapped here; new saves use `local_timezone` only.

Connection and UI fields:

- `connection_code`: Saved LAN/WebSocket connection code for clients and Edge SDKs.
- `ui_dark_mode`: UI dark mode preference. Default: `true`.
- `lan_secret`: Local LAN pairing secret. Usually managed by Yumi.

Memory fields:

- `memory_max_recent_messages`: Recent same-session messages included in context. Default: `30`.
- `memory_max_related_messages`: Related cross-session memory snippets included in context. `0` disables cross-session related memory. Default: `15`.

Tool policy fields:

- `local_tools_always_allow`: Server-local tool names that do not require confirmation.
- `local_tools_force_confirm`: Server-local tool names that always require confirmation.
- `edge_tools_enable_dynamic_routing`: Rank and cap Edge tools per turn. Default: `true`.
- `edge_tools_retrieval_limit`: Max dynamically retrieved Edge tool schemas exposed per turn. Pinned tools, forced follow-up tools, and tools on an explicitly mentioned edge may be added outside this cap. Default: `20`.
- `core_tools_always_include`: Keep core server tools loaded when enabled. Default: `true`.
- `core_tools_allow_disable`: Allow core tools to be disabled by tool policy/UI. Default: `true`.

Telegram fields:

- `telegram_bot_token`: Telegram Bot API token from BotFather. Environment variable: `TELEGRAM_BOT_TOKEN`.
- `telegram_allowed_user_ids`: Optional numeric Telegram user allowlist. Empty means no allowlist.

Discord fields:

- `discord_bot_token`: Discord bot token from the Developer Portal. Environment variable: `DISCORD_BOT_TOKEN`.
- `discord_allowed_user_ids`: Optional numeric Discord user allowlist. Empty means no allowlist.

LINE fields:

- `line_channel_secret`: LINE Messaging API channel secret.
- `line_channel_access_token`: LINE channel access token.
- `line_bot_port`: Port for the LINE webhook sidecar. Default: `8788`.
- `line_allowed_user_ids`: Optional LINE user allowlist. Empty means no allowlist.

Proactive messaging fields:

- `proactive_mode`: How proactive outbound messages are chosen: `off` (none), `smart` (probabilistic idle-aware check-ins + unreplied follow-ups), or `scheduled` (fixed local times and/or a fixed interval). Default after migrate: `off` when `proactive_enabled` is false or absent; **`smart`** when legacy JSON has `proactive_enabled: true` but no `proactive_mode`. Unknown values are treated as `off`.  
  **`yumi --config` writes this key explicitly** alongside the legacy toggle below.
- `proactive_enabled`: **Legacy / mirror.** Kept in JSON for compatibility; it is **synced from `proactive_mode`** on load (`true` when mode is `smart` or `scheduled`). Prefer setting `proactive_mode` for new configs.
- `proactive_schedule_times`: For `scheduled` mode only: list of local wall-clock times as `HH:MM` strings, interpreted in `local_timezone` (e.g. `["09:00", "13:30", "20:00"]`). Can be combined with `proactive_schedule_interval_minutes`.
- `proactive_schedule_interval_minutes`: For `scheduled` mode: send at most once per this many minutes (integer `5`–`10080`), or `null` to disable interval-based triggers. Can be combined with `proactive_schedule_times` (either may trigger a send attempt).
- `proactive_schedule_require_idle`: Default `true`. When `true`, scheduled sends respect `proactive_min_idle_minutes` so the bot does not interrupt right after user or proactive activity. Set `false` to allow sends solely constrained by quiet hours and daily limit.
- `proactive_channels`: Channels to use. First version supports `telegram`. Default: `["telegram"]`.
- `proactive_session_ids`: Target sessions, for example `["tg_123456"]`. Empty means no target.
- `proactive_daily_limit`: Max proactive sends per session per calendar day in `local_timezone`. Default: `4`.
- `proactive_quiet_hours`: Quiet-hour window on the **local wall clock** defined by `local_timezone`, such as `22:30-08:30`. Default: `00:30-08:30`.
- `proactive_check_interval_seconds`: Approximate background check interval (minimum `60`). Default: `900`.
- `proactive_check_interval_jitter_ratio`: Randomizes each sleep in `[interval*(1−r), interval*(1+r)]` (clamped to 60–86400s) so checks are not perfectly periodic. Default: `0.15`; set to `0` for a fixed interval.
- `proactive_min_idle_minutes`: Minimum idle time after user/proactive activity before a check-in. Default: `45`.
- `proactive_unreplied_escalation_minutes`: Base minutes before an unreplied follow-up can be sent again. Default: `180`.
- `proactive_unreplied_escalation_jitter_ratio`: Scales the above by a **stable** factor per `(session_id, last_proactive_at)` in `[1−r, 1+r]`. Default: `0` (exact minutes); try `0.12` for less mechanical follow-ups.
- `proactive_check_in_probability`: Probability each **eligible** check emits a random check-in (when not in the unreplied escalation path). Used in **`smart`** mode only. Default: `0.35`.
- `proactive_smart_naturalness`: Natural interaction style for **`smart`** mode only: `off`, `subtle`, or `balanced`. Default: `balanced`. This keeps the active system prompt in charge of the role while making random check-ins and unreplied follow-ups less notification-like.
- `proactive_smart_max_unreplied_followups`: Maximum unreplied smart follow-ups before Yumi gives the user space. Default: `4`.
- `proactive_profile`: Open profile label. Built-in hints include `default`, `natural`, `adaptive`, `companion`, `tutor`, and `coach`, but custom labels are allowed.
- `proactive_profile_prompt`: Custom proactive style instructions. When set, this has priority over built-in profile hints.
- `proactive_tone_intensity`: Follow-up intensity. Suggested values: `gentle`, `medium`, `strong`. Default: `gentle`.

Speech-to-text fields:

- `stt_provider`: Speech-to-text provider. `disabled` by default. `whisper` runs locally; `openai`, `gemini`, `dashscope`, and `grok` are no-download cloud backends that reuse the matching provider API key (`openai_api_key`, `gemini_api_key`, the shared DashScope `tts_api_key` / `DASHSCOPE_API_KEY`, and `grok_api_key` / `XAI_API_KEY` respectively).
- `stt_backend`: Whisper backend (only used when `stt_provider = whisper`). Default: `faster-whisper`.
- `stt_model`: Model name. Whisper: `base`, `small`, `turbo`, … ; OpenAI: `gpt-4o-mini-transcribe` (default), `gpt-4o-transcribe`, `whisper-1`; Gemini: `gemini-2.5-flash` (default); DashScope: `qwen3-asr-flash`; Grok auto-detects and ignores this field.
- `stt_model_dir`: Optional Whisper model cache directory. `null` uses Yumi's default (cloud providers ignore it).
- `stt_language`: Language hint. Default: `auto`.

Voice (microphone wake-word) fields — only consulted when running `yumi --server --voice`:

- `voice_wake_word`: Wake phrase shown in banner output. Default: `hi yumi`. The actual matcher is the `.ppn` model below.
- `voice_porcupine_access_key`: Picovoice access key. Environment variable: `PV_ACCESS_KEY`.
- `voice_porcupine_keyword_path`: Filesystem path to a `.ppn` keyword file trained at [console.picovoice.ai](https://console.picovoice.ai/). When `null`, Yumi falls back to the built-in `jarvis` keyword (loud warning at startup).
- `voice_porcupine_sensitivity`: Wake-word sensitivity, `0.0`–`1.0`. Higher catches more but false-fires more. Default: `0.5`.
- `voice_input_device`: Optional `sounddevice` device index. `null` uses the OS default microphone.
- `voice_vad_aggressiveness`: WebRTC VAD aggressiveness, `0`–`3`. Higher is stricter about classifying frames as speech. Default: `2`.
- `voice_silence_ms`: Trailing silence (ms) that ends an utterance. Default: `800` (minimum `100`).
- `voice_max_utterance_ms`: Hard cap (ms) for one utterance, even without silence. Default: `15000` (minimum `1000`).
- `voice_owner_id`: Stable identifier for the voice session id (`voice_<owner>`). Set this to your Telegram user id to interleave voice and Telegram turns in each prompt. `null` falls back to `$USER`.

Chat NDJSON tracing (optional): from Telegram (`/start_log` / `/end_log`), LINE, `yumi --chat`, or `PUT /config/chat-debug`, the server appends one line per JSON record to `YUMI_DEBUG_DIR/chat_trace/<session>/....ndjson` for that qualified `session_id`. Logs may contain prompts, model output, and tool args (privacy: do not share). State is in-memory only (restart clears active tracing).

## Environment Variables

### Model & API Keys

| Variable | Description |
|---|---|
| `YUMI_CHAT_PROVIDER` | Override chat provider (`ollama`, `openai`, `gemini`, `claude`, `deepseek`, `grok`) |
| `YUMI_CHAT_MODEL` | Override chat model |
| `YUMI_EMBEDDING_PROVIDER` | Override embedding provider |
| `YUMI_EMBED_MODEL` | Override embedding model |
| `OPENAI_API_KEY` | OpenAI-compatible API key |
| `OPENAI_BASE_URL` | Custom OpenAI-compatible base URL |
| `GEMINI_API_KEY` | Gemini API key |
| `ANTHROPIC_API_KEY` | Anthropic Claude API key |
| `DEEPSEEK_API_KEY` | DeepSeek API key (when `chat_provider` is `deepseek`) |
| `DEEPSEEK_BASE_URL` | Optional DeepSeek API base URL (defaults to `https://api.deepseek.com`) |
| `XAI_API_KEY` | xAI Grok API key (when `chat_provider` is `grok`) |
| `XAI_BASE_URL` | Optional Grok API base URL (defaults to `https://api.x.ai/v1`) |
| `OLLAMA_HOST` | Ollama server URL (default `http://127.0.0.1:11434`; useful when Ollama runs on a different host or in Docker) |
| `YUMI_DEBUG_DIR` | Override directory for debug artifacts (default `~/.yumi/debug`; chat traces use `chat_trace/` under this) |
| `YUMI_CHAT_DEBUG_REDACT_IMAGE_DATA` | When `1` / `true`, inline `data:...;base64,...` image URLs inside trace NDJSON `llm_provider_request` records are replaced with short placeholders (smaller files). Does not change what is sent to the model—only what is written to disk. When chat-debug tracing is enabled for a session, traces already include the full composed provider `messages` and `tools` after `compose_messages`. |

### Server & Connection

| Variable | Description |
|---|---|
| `YUMI_SERVER_URL` | Manual direct server URL (default `http://127.0.0.1:8000`) |
| `YUMI_CONNECTION_CODE` | Connection code for edge SDKs (LAN code or WebSocket URL) |

### Memory

| Variable | Description |
|---|---|
| `YUMI_MEMORY_MAX_RECENT` | Max recent messages included in context (integer) |
| `YUMI_MEMORY_MAX_RELATED` | Max semantically related memories included in context (integer) |

### Chat Behaviour

| Variable | Description |
|---|---|
| `YUMI_CHAT_APPEND_CURRENT_TIME` | Set to `1`/`true` to append the current time to the system prompt |
| `YUMI_CHAT_APPEND_TOOL_INSTRUCTION` | Set to `1`/`true` to append tool-use instructions to the system prompt |
| `YUMI_LOCAL_TIMEZONE` | IANA timezone for local wall clock (chat time, proactive clock, quiet hours, daily limit). Overrides `YUMI_PROACTIVE_QUIET_HOURS_TIMEZONE` if both are set |

### Proactive Messaging

| Variable | Description |
|---|---|
| `YUMI_PROACTIVE_MODE` | `off`, `smart`, or `scheduled` (overrides file when set). When **`YUMI_PROACTIVE_ENABLED` is set** but `YUMI_PROACTIVE_MODE` is **not** set, mode becomes `smart` if enabled is true, else `off`. |
| `YUMI_PROACTIVE_ENABLED` | Legacy toggle: when set **without** `YUMI_PROACTIVE_MODE`, forces mode to `smart`/`off`. After load, `proactive_enabled` always mirrors `(proactive_mode != off)`. |
| `YUMI_PROACTIVE_CHANNELS` | Comma-separated channels, currently `telegram` |
| `YUMI_PROACTIVE_SESSION_IDS` | Comma-separated target sessions, for example `tg_123456` |
| `YUMI_PROACTIVE_DAILY_LIMIT` | Max proactive sends per session per day (default `4`) |
| `YUMI_PROACTIVE_QUIET_HOURS` | Quiet-hour window on the wall clock of `YUMI_LOCAL_TIMEZONE` / config `local_timezone` (or UTC if unset), e.g. `22:30-08:30` |
| `YUMI_PROACTIVE_QUIET_HOURS_TIMEZONE` | **Legacy.** IANA timezone; prefer `YUMI_LOCAL_TIMEZONE`. Used only when `YUMI_LOCAL_TIMEZONE` is unset |
| `YUMI_PROACTIVE_CHECK_INTERVAL_SECONDS` | Background check interval (minimum `60`, default `900`). Sleep uses jitter (below); for **`scheduled`** mode this also widens the matching window for fixed clock times (with a minimum grace). |
| `YUMI_PROACTIVE_CHECK_INTERVAL_JITTER_RATIO` | Sleep jitter ratio `0`–`0.5` (default `0.15`; `0` = fixed interval) |
| `YUMI_PROACTIVE_MIN_IDLE_MINUTES` | Minimum idle time after user/proactive activity before a check-in (default `45`) |
| `YUMI_PROACTIVE_UNREPLIED_ESCALATION_MINUTES` | Base minutes before an unreplied follow-up can escalate (default `180`). **`smart`** mode only. |
| `YUMI_PROACTIVE_UNREPLIED_ESCALATION_JITTER_RATIO` | Stable random scale `0`–`0.5` for escalation delay (default `0`) |
| `YUMI_PROACTIVE_CHECK_IN_PROBABILITY` | Probability of a random check-in when eligible (default `0.35`). **`smart`** mode only. |
| `YUMI_PROACTIVE_SMART_NATURALNESS` | `off`, `subtle`, or `balanced` natural interaction style for **`smart`** mode only. |
| `YUMI_PROACTIVE_SMART_MAX_UNREPLIED_FOLLOWUPS` | Maximum unreplied smart follow-ups before giving the user space. |
| `YUMI_PROACTIVE_SCHEDULE_TIMES` | Comma-separated local times `HH:MM` for **`scheduled`** mode (same timezone as `local_timezone`) |
| `YUMI_PROACTIVE_SCHEDULE_INTERVAL_MINUTES` | Fixed interval in minutes (`5`–`10080`) for **`scheduled`** mode |
| `YUMI_PROACTIVE_SCHEDULE_REQUIRE_IDLE` | `1`/`true` or `0`/`false`; matches `proactive_schedule_require_idle` |
| `YUMI_PROACTIVE_PROFILE` | Open profile label, for example `default`, `companion`, `tutor`, `coach`, or custom |
| `YUMI_PROACTIVE_PROFILE_PROMPT` | Custom proactive behavior prompt, overrides preset guidance |
| `YUMI_PROACTIVE_TONE_INTENSITY` | `gentle`, `medium`, or `strong` |

For a more frequent companion-style setup, prefer editing the same keys in `~/.yumi/config.json` after running `yumi --config`.

### Speech-to-Text

| Variable | Description |
|---|---|
| `YUMI_STT_PROVIDER` | STT provider (`disabled`, `whisper`, `openai`, `gemini`, `dashscope`, or `grok`; default `disabled`) |
| `YUMI_STT_BACKEND` | Whisper backend (`faster-whisper`; default) |
| `YUMI_STT_MODEL` | Multilingual Whisper model (`tiny`, `base`, `small`, `medium`, `large`, or `turbo`) |
| `YUMI_STT_MODEL_DIR` | Model cache directory (default `~/.yumi/models/whisper`) |
| `YUMI_STT_LANGUAGE` | STT language hint (default `auto`) |
| `HF_TOKEN` or `HUGGING_FACE_HUB_TOKEN` | Optional Hugging Face Hub token for higher rate limits when downloading Whisper weights (same env vars Hugging Face tools expect). |

Put `HF_TOKEN=hf_...` in **`~/.yumi/.env`** or **`./.env`** if you want; Yumi loads those files early via `python-dotenv` (without overwriting variables already set in your shell).

Speech-to-text is optional and disabled by default. Run `yumi --setup` to enable local multilingual Whisper for Telegram voice/audio, LINE audio, audio uploads in the web UI, or `/transcribe <path>` in `yumi --chat`.

`pip install yumi-agent` includes the Whisper runtime, but **model weight files** are large and are not in the git repository or wheel. When you pick an STT model in `yumi --setup`, Yumi **downloads the weights to** `~/.yumi/models/whisper` (or your chosen directory) so the first real voice message is not stuck waiting on the network.

The **cloud STT providers** (`openai`, `gemini`, `dashscope`, `grok`) need no extra and no model download — they ship in the base install and reuse the API key you already configured for that provider. Pick one in `yumi --setup` when you want transcription without local model weights; `openai` additionally honors `openai_base_url` (`OPENAI_BASE_URL`) for OpenAI-compatible proxy / Azure endpoints.

The setup wizard exposes only multilingual Whisper models: `tiny`, `base`, `small`, `medium`, `large`, and `turbo`. `base` is the recommended starter choice; `tiny` is lighter, while `small` and above trade more disk/CPU/GPU resources for better accuracy.

### Tool Routing

| Variable | Description |
|---|---|
| `YUMI_EDGE_TOOLS_DYNAMIC_ROUTING` | Set to `1`/`true` to rank and cap Edge tools per chat turn (default `true`) |
| `YUMI_EDGE_TOOLS_RETRIEVAL_LIMIT` | Number of Edge tool schemas exposed per chat turn, `0`-`200` (default `20`) |

Core Yumi tools are always loaded when enabled. Edge tools are registered in full, but when dynamic routing is enabled Yumi embeds the current request and Edge tool retrieval documents, then exposes only the most relevant Edge tools to the model. If embeddings are unavailable, Yumi falls back to deterministic lexical matching.

You can also update the saved config from the terminal:

```bash
yumi --tool-routing
yumi --tool-routing --edge-tools-limit 30
yumi --tool-routing --disable-edge-tool-routing
yumi --tool-routing --enable-edge-tool-routing --edge-tools-limit 20
```

### Logging

| Variable | Description |
|---|---|
| `YUMI_LOG_LEVEL` | Python logging level for server/UI (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`; default `WARNING`) |
| `YUMI_HTTP_LOG` | Set to `1`/`true` to log every `httpx`/`httpcore` request at INFO (noisy; default is to silence them so Yumi log lines stay visible) |

### CORS & Security

| Variable | Description |
|---|---|
| `YUMI_CORS_ORIGINS` | Comma-separated browser origins allowed to call the core API. Default: localhost origins only |
| `YUMI_CORS_ALLOW_CREDENTIALS` | Set to `1`/`true` to allow browser credentials on the core API |

### Edge SDK

| Variable | Description |
|---|---|
| `EDGE_NAME` | Override edge device display name (defaults to system hostname) |
| `YUMI_TOOL_CONFIRMATION_PATH` | Custom path for the tool confirmation policy file |

### Telegram

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from [@BotFather](https://t.me/BotFather) (optional Telegram bridge) |
| `TELEGRAM_ALLOWED_USER_IDS` | Comma-separated Telegram user IDs allowed to use the bot; empty = no restriction |

### Discord

| Variable | Description |
|---|---|
| `DISCORD_BOT_TOKEN` | Bot token from the [Discord Developer Portal](https://discord.com/developers/applications) (optional Discord bridge) |
| `DISCORD_ALLOWED_USER_IDS` | Comma-separated Discord user IDs allowed to use the bot; empty = no restriction |

### Voice

| Variable | Description |
|---|---|
| `YUMI_VOICE_ENABLED` | Set automatically by `yumi --server --voice`. `1` makes the API lifespan start the wake-word loop; you should not normally set this by hand. |
| `YUMI_VOICE_OWNER_ID` | Same as `voice_owner_id` in config. Set automatically by the CLI helpers. |
| `PV_ACCESS_KEY` | Picovoice access key. Overrides `voice_porcupine_access_key` when both are set. |

## Telegram

Telegram-related dependencies (`python-telegram-bot`, `httpx`) are included in the default install; no optional extras are required.

### Setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token.
2. Configure the token (any one of the following):
   - Set environment variable `TELEGRAM_BOT_TOKEN`
   - Add `"telegram_bot_token": "..."` to `~/.yumi/config.json`
   - Run `yumi --server --telegram` or `yumi --telegram` without a token set -- Yumi will prompt you to paste it and saves it to `~/.yumi/config.json`
3. Optionally restrict access: set `TELEGRAM_ALLOWED_USER_IDS` or add `"telegram_allowed_user_ids"` in config.
4. To accept voice/audio messages, enable STT in `yumi --setup` (Whisper weights are downloaded during setup when you select a model).

### Running

- **`yumi --server --telegram`** (recommended) -- starts the API and the Telegram bot together on one machine.
- **`yumi --telegram`** -- runs only the Telegram bot, connecting to the API like `yumi --chat` (LAN code / server URL).

### Timer & Push Notifications

When a timer fires for a Telegram session (`tg_<user_id>`), the **API process** calls Telegram `sendMessage` directly. For this to work, the bot token must be available on the machine running `yumi --server`.

> If you run `yumi --telegram` on your laptop but `yumi --server` on a remote host, you must also configure the same bot token on the remote host (via env or config file), or use `yumi --server --telegram` on a single machine.

### Troubleshooting

- **Restart** the API after changing the token if it was already running.
- If messages fail, check server logs -- Telegram often returns HTTP 200 with `ok: false` (e.g. user blocked the bot, wrong chat_id). Run with `YUMI_LOG_LEVEL=DEBUG` for details.
- **Delayed actions** ("in 1 minute do X") only work if the model actually calls the `set_timer` / `schedule_task` tool. Plain text promises do nothing. Check with `YUMI_LOG_LEVEL=INFO` -- you should see `Tool call: set_timer session_id=...` in the logs. If not, try rephrasing or using a model with stronger tool-use support.

## Discord

Discord works out of the box — `discord.py` ships with `yumi-agent` (no extra needed). The bot keeps an outbound gateway connection — no public webhook or URL is needed, the same self-hosted spirit as Telegram polling. Sessions are keyed by `dc_<user_id>`, and chat flows through the same `POST /chat` NDJSON stream as Telegram.

### Setup

1. Create an application + bot in the [Discord Developer Portal](https://discord.com/developers/applications) and copy the bot token.
2. Under the bot settings, enable the **Message Content** privileged intent (Yumi reads message text to forward it to `/chat`).
3. Configure the token (any one of the following):
   - Set environment variable `DISCORD_BOT_TOKEN`
   - Add `"discord_bot_token": "..."` to `~/.yumi/config.json`
   - Run `yumi --server --discord` or `yumi --discord` without a token set -- Yumi will prompt you to paste it and saves it to `~/.yumi/config.json`
4. Optionally restrict access: set `DISCORD_ALLOWED_USER_IDS` or add `"discord_allowed_user_ids"` in config.
5. Invite the bot to a server (or DM it directly) so it can receive your messages.

### Running

- **`yumi --server --discord`** (recommended) -- starts the API and the Discord bot together on one machine.
- **`yumi --discord`** -- runs only the Discord bot, connecting to the API like `yumi --chat` (LAN code / server URL).

### Behaviour notes

- Commands use the `!` prefix: `!clear`, `!model`, `!system`, `!timers`, `!cancel_timer <id>`, `!start_log`, `!end_log`, `!help`.
- Tool confirmations are presented as Discord buttons (Deny / Allow / Always allow) via `discord.ui.View`.
- Like Telegram, timer pushes (`dc_<user_id>` sessions) require the bot token to be present on the machine running `yumi --server`; the API process delivers them over Discord's REST API.

## LINE

Yumi exposes `POST /line/webhook`, verifies `X-Line-Signature`, and forwards chat to the same `POST /chat` NDJSON flow as Telegram. Tool confirmations use **Flex** messages with postback buttons. Sessions are keyed by `line_<user_id>`.

### Setup

1. Create a Messaging API channel in the [LINE Developers Console](https://developers.line.biz/) and copy the channel secret + channel access token.
2. Configure credentials (any one of the following):
   - Set environment variables `LINE_CHANNEL_SECRET` and `LINE_CHANNEL_ACCESS_TOKEN`
   - Add `"line_channel_secret"` and `"line_channel_access_token"` to `~/.yumi/config.json`
   - Run `yumi --server --line` or `yumi --line` without credentials set -- Yumi will prompt and save them
3. Optionally restrict access via `LINE_ALLOWED_USER_IDS` or `"line_allowed_user_ids"` in config.

### Running

- **`yumi --server --line`** (recommended) -- starts the API and a webhook server on `LINE_BOT_PORT` (default `8788`). Set the LINE channel webhook URL to `https://<your-host>:8788/line/webhook` (TLS required in production).
- **`YUMI_LINE_INCORE=1`** -- mounts `POST /line/webhook` on the **same** FastAPI app as the core API (single port). Still configure credentials on the API process so timer pushes work.
- **`yumi --line`** -- webhook sidecar only; point `YUMI_SERVER_URL` at your core API.

### Behaviour notes

- `/clear`, `/model`, and `/system` work the same as Telegram.
- `LINE_DISABLE_PUSH=1` suppresses outbound push messages while testing.
- Like Telegram, timer pushes require the bot credentials to be present on the machine running `yumi --server`.

## Voice

`yumi --server --voice` attaches a microphone wake-word session to the running API. After the wake word ("hi yumi") fires, Yumi records until you pause, transcribes with the configured Whisper model, and sends the transcript through the same `/chat` flow used by `--chat` / `--ui` / Telegram. Replies are spoken back aloud via TTS (and logged) — see [Spoken replies (TTS)](#spoken-replies-tts) below.

### Install

`pip install yumi-agent` includes `sounddevice` (mic capture), `webrtcvad-wheels` (voice activity detection), `pvporcupine` (wake-word), and `faster-whisper` (transcription). Whisper weights are downloaded the first time you run `yumi --setup` and pick a model.

### Setup

1. **Picovoice access key** — sign up at [console.picovoice.ai](https://console.picovoice.ai/) (free for personal use) and copy your access key. Either:
   - export `PV_ACCESS_KEY=...` in the shell that launches Yumi, or
   - save `voice_porcupine_access_key` in `~/.yumi/config.json`.
2. **Train a "hi yumi" wake-word** — Picovoice's built-in keywords do not include "hi yumi". In the console, create a custom keyword for English (or your language), download the resulting `.ppn` file, and save it (suggested: `~/.yumi/voice/hi-yumi.ppn`). Set `voice_porcupine_keyword_path` to that path. Without a custom file, Yumi falls back to the built-in `jarvis` keyword and prints a warning at startup.
3. **Microphone permission** — on macOS, grant your terminal app microphone access in *System Settings → Privacy & Security → Microphone*. Without permission, `sounddevice` returns silent audio and the VAD never triggers.
4. **Tune `voice_owner_id`** — set this to a stable identifier (your Telegram/Discord/LINE user id, or another stable account id). The voice session id is `voice_<owner_id>`; matching the suffix with `tg_<id>` / `dc_<id>` / `line_<id>` / `chat_<id>` is what makes cross-channel context (below) work.

### Running

- **`yumi --server --voice`** — API + voice loop in one process tree. The CLI sets `YUMI_VOICE_ENABLED=1` and `YUMI_VOICE_OWNER_ID` for the API child process; the API lifespan starts a background asyncio task for the loop and cancels it on shutdown.
- **`yumi --server --telegram --voice`** — same, plus the Telegram bot. All three (API, bot, voice) live in the same process tree and are stopped together by `Ctrl+C`.

### Cross-channel context

Voice / Telegram / Discord / LINE / `--chat` each persist to their own session (`voice_alice`, `tg_alice`, `dc_alice`, `line_alice`, `chat_alice`). Each chat turn fetches the most recent N messages from the **current** session **plus** any sibling sessions that share the owner suffix, merges them by timestamp, and renders sibling turns with a `(via voice)` / `(via telegram)` / `(via discord)` / `(via line)` / `(via chat)` tag so the model can distinguish channels. `yumi --chat` uses random UUID session ids by default, so its history is included only when you pass an explicit `session_id` matching the voice owner.

The merge happens in `yumi/core/features/memory/context.py::ContextBuilder._recent_transcript`. The cap is roughly twice `memory_max_recent_messages` after merge to keep peers from crowding out the current channel. There is no schema change — peer messages are read with a single `session_id IN (...)` query against the existing `chat_history` LanceDB table.

### Voice loop details

- **Frame size** — 16 kHz mono int16; Porcupine picks the frame length (typically 32 ms / 512 samples) and the same blocks are sliced into 30 ms windows for WebRTC VAD.
- **End-of-utterance** — flush on `voice_silence_ms` of trailing silence, or `voice_max_utterance_ms` total length, whichever first.
- **Whisper warm-up** — the API lifespan transcribes 1 s of silence at boot, so the first real utterance does not pay the full cold-start delay.
- **Errors** — transcription / dispatch errors are logged and swallowed; the loop keeps listening. `KeyboardInterrupt` (Ctrl+C) cleanly stops the audio stream and closes the Porcupine handle.

### v1 limits

- Single owner per server instance — multiple humans sharing a microphone all get the same `voice_<owner>` session.
- macOS / Linux desktop only. Docker has no microphone, and voice cannot run on a remote `--server`.
- No barge-in. The model finishes its turn before the next utterance is processed.

## Spoken replies (TTS)

Yumi can speak its replies. In voice mode (`--server --voice`) replies are spoken automatically; on Telegram / Discord, `/voice on` (`!voice on`) switches a chat to audio replies; `yumi --speak "hello"` is a quick smoke test. Configure it in `yumi --setup` (step 4) or directly in `~/.yumi/config.json`.

### Backends

| `tts_provider` | What it is | Needs |
|---|---|---|
| `system` | OS speech command (Windows SAPI, macOS `say`, Linux `espeak`/`espeak-ng`) | nothing (zero-dependency default) |
| `openai` | OpenAI TTS (`gpt-4o-mini-tts` / `tts-1` / `tts-1-hd`) | `openai_api_key` (no extra; in the base install) |
| `gemini` | Gemini native audio TTS (`gemini-3.1-flash-tts-preview`) | `gemini_api_key` / `GEMINI_API_KEY` (no extra; in the base install) |
| `dashscope` | Qwen3-TTS via the Alibaba Cloud DashScope API | `DASHSCOPE_API_KEY` (no extra; in the base install) |
| `grok` | xAI/Grok voice TTS | `grok_api_key` / `XAI_API_KEY` (no extra; in the base install) |
| `qwen` | Qwen3-TTS run locally | a GPU + PyTorch (see note); `pip install yumi-agent[tts-local]` |

For `system`, `openai`, `gemini`, `dashscope`, and `grok`, `pip install yumi-agent` includes the required Python packages. **Local `qwen` is the one exception**: it runs on PyTorch, and GPU-specific builds are large and platform-specific, so they cannot be part of the default install. Install PyTorch for your device from <https://pytorch.org/get-started/locally/> **first**; then `yumi --setup` will install `qwen-tts` on top. CUDA/NVIDIA is the fastest and most reliable path. Apple MPS can work on some Apple Silicon Macs, but is more experimental and usually slower. The provider auto-detects the device (CUDA → Apple MPS → CPU), and the first synthesis downloads the model weights (~GBs, with a progress bar).

### Config keys

- `tts_provider` — `disabled` (default) / `system` / `openai` / `gemini` / `dashscope` / `grok` / `qwen`.
- `tts_voice` — voice/speaker name. OpenAI: `alloy` (default), `nova`, `shimmer`, … ; Gemini: `Kore` (default), … ; DashScope: `Cherry`, `Serena`, `Ethan`, … ; Grok: `eve` (default), `ara`, `rex`, … ; local qwen: `Ryan`, `Vivian`, `Serena`, … ; `system` uses the OS default unless set.
- `tts_model` — backend model id. OpenAI defaults to `gpt-4o-mini-tts`; Gemini to `gemini-3.1-flash-tts-preview`; DashScope to `qwen3-tts-flash`; local qwen to `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice`. Grok has no model setting.
- `tts_api_key` — DashScope key (or set `DASHSCOPE_API_KEY`). OpenAI TTS reuses `openai_api_key`, not this field.
- `tts_language` — `auto` (default) or a language name (`English`, `Chinese`, …).

Environment: `YUMI_TTS_PROVIDER`, `YUMI_TTS_VOICE`, `YUMI_TTS_MODEL`, `YUMI_TTS_LANGUAGE` override the config keys above; `DASHSCOPE_API_KEY`, `DASHSCOPE_BASE_URL` (defaults to the international endpoint; set the Beijing endpoint for China) supply the DashScope credentials.

### Bridge replies

On Telegram / Discord, audio replies are sent as a normal audio file (WAV) with the text as caption — not a native voice note (which would require OGG/Opus re-encoding). If synthesis or upload fails, Yumi falls back to a plain-text reply.

## Data Storage

| Path | Contents |
|---|---|
| `~/.yumi/config.json` | Model config, prompt config, saved connection code |
| `~/.yumi/memory/` | Session history and embeddings |

`config.json` can hold **multiple provider API keys at once** (`openai_api_key`, `gemini_api_key`, `claude_api_key`, `deepseek_api_key`, `grok_api_key`, and optional provider base URLs). You can use the dedicated `deepseek` and `grok` providers, or point `openai_base_url` at another OpenAI-compatible endpoint. Environment variables still win when set. `yumi --setup` only asks for what the chosen chat/embedding providers need; for local embeddings it downloads a multilingual FastEmbed model directly from the CLI. You can add other keys later via the web UI **Model Configuration** dialog or by editing `config.json`, so switching providers does not require re-entering keys once they are saved.

To clear only memory and embeddings (keeping config):

```bash
yumi --cleanup-memory
```

To clear local model caches managed by Yumi while keeping config, memory, prompts, and connection info:

```bash
yumi --cleanup-models
```

This removes `~/.yumi/models/` (Whisper, FastEmbed, and local Qwen3-TTS caches). Ollama keeps models in its own store; to also remove the Ollama models referenced by your current Yumi config:

```bash
yumi --cleanup-models --include-ollama
```

To delete all Yumi user data (`~/.yumi/`):

```bash
yumi --cleanup
```

## Connection Codes

When `yumi --server` starts, it prints:

- A permanent LAN code
- A temporary 24-hour LAN code

You can use those codes from `--chat`, `--ui`, `--edge`, or from any SDK.

> **A connection code is a connection string, not a credential.** It just
> encodes the server host/port. The local server has no built-in user auth, so
> reaching the host/port is what grants access; the optional `lan_secret` HMAC
> only detects tampering when both ends share the secret. The server binds to
> loopback by default — expose it on a LAN only on a trusted network (`yumi
> --server --host 0.0.0.0`). See [Edge Tools → Connection Code
> Formats](EDGE_TOOLS.md#connection-code-formats).

Yumi saves the last successful connection code in `~/.yumi/config.json` and reuses it automatically.

## Remote Access

For personal remote access, the recommended path is Tailscale.

Typical flow:

1. Install Tailscale on the server and the remote device
2. Put both on the same Tailnet
3. Run `yumi --server` on the host machine
4. Use the Tailscale hostname or IP from `yumi --ui` or `yumi --chat`

## Deployment Hardening

Yumi defaults to **local-first** operation. Browser CORS is limited to localhost-style origins by default, and browser credentials are disabled unless you explicitly opt in.

- Keep the core API on `127.0.0.1` unless you intentionally trust your LAN.
- Prefer Tailscale or another private network over exposing the core API directly.
- If you need third-party browser pages to call the core API, set `YUMI_CORS_ORIGINS` explicitly instead of relying on permissive wildcards.

## Docker

Build and run the API server (data persisted in a Docker volume for `/root/.yumi`):

```bash
docker compose up --build
```

To pass model configuration, uncomment or add environment variables in `docker-compose.yml`:

```yaml
environment:
  YUMI_CHAT_PROVIDER: openai
  YUMI_CHAT_MODEL: gpt-5.5
  OPENAI_API_KEY: sk-...
```

See [`docker-compose.yml`](../docker-compose.yml) and [`Dockerfile`](../Dockerfile). You still need a reachable LLM (for example Ollama on the host); set `OLLAMA_HOST` or model env vars as appropriate.
