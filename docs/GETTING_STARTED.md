# Getting Started

## Requirements

- Python 3.10+
- [Ollama](https://ollama.com/) only if you choose Ollama chat or Ollama embeddings
- API keys for cloud providers such as OpenAI or Gemini

## Install

If you are installing from PyPI:

```bash
pip install yumi-agent
```

If you are installing from source:

```bash
git clone https://github.com/wenxijiao/yumi-agent.git
cd Yumi
pip install .
```

For development:

```bash
pip install -e ".[dev]"
```

### PyPI and npm

| Artifact | Install |
|----------|---------|
| **Python app & server** | PyPI package name: **`yumi-agent`** (publish when ready). Until then: `pip install .` from a clone. |
| **TypeScript SDK** | npm package name: **`yumi-sdk`** ([`yumi/sdk/typescript/package.json`](../yumi/sdk/typescript/package.json)). Until published: copy from this repo or use `yumi --edge`. |
| **Go, Swift, Java, C++, Rust, Kotlin, Dart, UE5** | Vendored from [`yumi/sdk/`](../yumi/sdk/README.md) or copied into your project via `yumi --edge`; not published as language-specific registry packages yet. |

Publishing tagged releases to PyPI and npm is documented in [CONTRIBUTING.md](../CONTRIBUTING.md#releases-pypi--npm).

### CI

Every push and pull request to `main` runs GitHub Actions: Python (`pytest`, `ruff`, `compileall`), TypeScript / C++ / Go / Swift / Java SDK builds, and other jobs defined in [`.github/workflows/ci.yml`](../.github/workflows/ci.yml).

## First Run

1. Start the server:

```bash
yumi --server
```

Keep this running in its own terminal. Open a second terminal for `yumi --chat`, `yumi --ui`, or `yumi --demo`.

2. On first run, Yumi guides you through:
   - Chat provider selection
   - Chat model selection
   - Embedding provider selection (cloud, local FastEmbed, Ollama, or skip)
   - Embedding model selection
   - Required API keys

3. To rerun setup later:

```bash
yumi --setup
```

## Providers

| Provider | Chat | Embedding | Notes |
|---|---|---|---|
| `ollama` | Yes | Yes | Local models, no API key needed |
| `openai` | Yes | Yes | Also works with OpenAI-compatible endpoints (including DeepSeek via `openai_base_url`) |
| `gemini` | Yes | Yes | Google Gemini |
| `fastembed` | No | Yes | Local multilingual embeddings installed/downloaded from the CLI |
| `claude` | Yes | No | Anthropic Claude (use another provider for embeddings) |
| `deepseek` | Yes | No | DeepSeek chat API; use another provider for embeddings |

You can mix providers — for example OpenAI for chat and Ollama for embeddings.

## Web UI

```bash
yumi --ui
```

The UI includes:

- **Chat**: session management, search, pinning, streaming replies
- **Tools**: server tools and connected edge devices
- **Settings**: models, prompts, appearance, runtime config

## Terminal Chat

```bash
yumi --chat
```

Useful commands:

| Command | Description |
|---|---|
| `/help` | Show commands |
| `/prompt` | Inspect prompt state |
| `/prompt set <text>` | Set session prompt |
| `/prompt default` | Reset session prompt |
| `/prompt global` | Show global prompt |
| `/prompt global set <text>` | Update global prompt |
| `/prompt global reset` | Reset built-in global prompt |
| `/model` | Show current model config |
| `/session` | Show current session ID |
| `/clear` | Clear current session |

## Voice (microphone wake-word)

`yumi --server --voice` attaches a microphone wake-word loop to the running API. Say "hi yumi" and the next sentence you speak is transcribed with Whisper and dispatched as a chat turn, in parallel with Telegram, Discord, `--chat`, and `--ui`.

```bash
pip install -e ".[voice,stt]"     # sounddevice, webrtcvad, pvporcupine, faster-whisper
yumi --setup                     # enable Whisper (stt_provider=whisper)
yumi --server --voice            # or:  yumi --server --telegram --voice
```

Required setup:

1. **Picovoice access key** — sign up at [console.picovoice.ai](https://console.picovoice.ai/) (free tier covers personal use). Set `PV_ACCESS_KEY` in the environment, or save `voice_porcupine_access_key` in `~/.yumi/config.json`.
2. **Wake-word file** — Picovoice's built-in keywords do **not** include "hi yumi"; train one in the console and download the `.ppn` file. Save it (suggested path: `~/.yumi/voice/hi-yumi.ppn`) and point `voice_porcupine_keyword_path` at it. Without a custom file Yumi falls back to the built-in `jarvis` keyword.
3. **Microphone permission** — on macOS, open *System Settings → Privacy & Security → Microphone* and enable the terminal you launch Yumi from. Without permission `sounddevice` silently produces zero-filled audio.

Speak after the server prints `voice: listening`. Each utterance produces log lines like:

```
voice: wake-word triggered
voice: utterance captured 1840 ms
voice: transcript='whats the weather in auckland'
voice: dispatching session=voice_alice
voice: reply session=voice_alice text='Currently 17 °C and partly cloudy.'
```

Voice writes to its own session, `voice_<voice_owner_id>`. When `voice_owner_id` matches a Telegram user id (`tg_<id>`) or a CLI session id (`chat_<id>`), Yumi automatically interleaves the most recent turns from those sibling sessions into each prompt — so you can ask in Telegram "what did I just say by voice?" and the answer is grounded in the spoken turns. The full list of voice-related fields lives in [Configuration → Voice](CONFIGURATION.md#voice).

v1 limits: text-only replies (no spoken response), single owner per server, no barge-in, only macOS / Linux desktop (Docker has no microphone). The first utterance can take 5–10 seconds because Whisper warms up on demand.

## Demo

Yumi ships with a dual-window demo suite that demonstrates one agent controlling
two independent Python applications at once.

```bash
yumi --server
yumi --demo
```

Keep `yumi --server` running in its own terminal, then launch `yumi --demo` from a second terminal.

The demo requires a graphical desktop session. On Linux, install Tk support first (for example `sudo apt install python3-tk` on Debian/Ubuntu).

This opens:

- `Smart Home` (`yumi.demo.smart_home`) — house devices and rooms (card grid)
- `Planner` (`yumi.demo.planner`) — tkinter schedule app: mini calendar + day timeline; tools `add_event`, `remove_event`, `update_event`, `get_schedule`, `clear_schedule`, `set_reminder`

Then open `yumi --chat` or `yumi --ui` and ask the agent to control both.

The demo windows are display-only (no in-GUI buttons). Both windows show the same status format (`Connected · EdgeName · Tools`) so users can quickly understand that one session controls two apps.

Try these one-line prompts:

- `Turn on the kitchen lights and add a "Cook dinner" event at 18:00 for 1 hour, category personal.`
- `Set thermostat to 22, and show me today's schedule.`
- `Lock the front door, add "Team standup" tomorrow at 10:00 for 30 minutes, category meeting.`
- `Turn off bedroom lamp, remove the "Lunch with Alex" event.`
- `Open garden gate, update "Code review" to start at 15:00 instead.`
- `Brew coffee, set a reminder for "Morning run" 15 minutes before.`

## Automated Tests

```bash
pip install -e ".[dev]"
pytest
```

See [TESTING.md](TESTING.md) for more details.

## Cleanup

```bash
yumi --cleanup
```

This removes `~/.yumi/`. Ollama and its model files are not touched.

To clear only saved chat memory and embeddings while keeping config and profiles:

```bash
yumi --cleanup-memory
```

This removes `~/.yumi/memory/` (and any legacy memory directory) but keeps model settings, prompts, and saved connection info.
