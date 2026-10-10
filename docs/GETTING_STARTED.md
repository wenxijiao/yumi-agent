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
cd yumi-agent
pip install .
```

For development:

```bash
pip install -e ".[dev]"
```

### PyPI and npm

| Artifact | Install |
|----------|---------|
| **Python app & server** | PyPI package name: **`yumi-agent`**. Source installs use `pip install .` from a clone. |
| **TypeScript SDK** | npm package name: **`yumi-sdk`** ([`yumi/sdk/typescript/package.json`](../yumi/sdk/typescript/package.json)). Source/template installs can copy from this repo or use `yumi --edge`. |
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
| `openai` | Yes | Yes | Also works with OpenAI-compatible endpoints via `openai_base_url` |
| `gemini` | Yes | Yes | Google Gemini |
| `fastembed` | No | Yes | Local multilingual embeddings downloaded from the CLI |
| `claude` | Yes | No | Anthropic Claude (use another provider for embeddings) |
| `deepseek` | Yes | No | DeepSeek chat API; use another provider for embeddings |
| `grok` | Yes | No | xAI Grok chat API; use another provider for embeddings |

You can mix providers — for example OpenAI for chat and Ollama for embeddings.

## Web UI

```bash
yumi --server      # in one terminal
yumi --ui          # opens the web UI in your browser
```

The web UI ships pre-built and is served by the core server itself (no Node, no
extra install). `yumi --ui` just opens your browser at the running server's
`/app` page.

The UI includes:

- **Chat**: session management, search, pinning, streaming replies, file upload, and voice (mic input + spoken replies)
- **Tools**: enable/disable server tools and connected edge devices, with per-tool confirmation gating
- **Debug**: a per-turn inspector for prompt layers, LLM rounds, tool calls, cache usage, finish reasons, and Edge routing health
- **Settings**: models, API keys, prompts, memory, voice, appearance, and edge-routing config
- **Schedules**, **Memory search**, a first-run **setup wizard**, and a **⌘K command palette**

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

Run `yumi --voice` on the computer with the microphone. Choose the local model
or sign in to Nexus, then say **Hey Yumi**. First-run wake-model download is
automatic; local mode starts a server if needed. Replies have a 20-second
wake-free follow-up window, and speaking during a reply interrupts it.

```sh
pip install -e .   # current source; this client requires the 0.0.5 release
yumi --voice
```

See [Hey Yumi voice](HEY_YUMI_VOICE_CLIENT.md) for installation/release status,
device selection, local speech setup, Nexus sign-in, and current limitations.

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

To delete only local model caches managed by Yumi:

```bash
yumi --cleanup-models
```

This removes `~/.yumi/models/` (Whisper, FastEmbed, and local Qwen3-TTS caches) while keeping config, memory, prompts, and connection info. Add `--include-ollama` to also remove the Ollama models referenced by your current Yumi config.

To clear only saved chat memory and embeddings while keeping config and profiles:

```bash
yumi --cleanup-memory
```

This removes `~/.yumi/memory/` (and any legacy memory directory) but keeps model settings, prompts, and saved connection info.
