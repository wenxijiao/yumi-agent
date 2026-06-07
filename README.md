# Kumi

[![CI](https://github.com/wenxijiao/kumi-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/wenxijiao/kumi-agent/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

**One API to let AI call functions in any language, on any device.**

Register a function. AI calls it. Python, Rust, Kotlin, Dart, C++, Swift, TypeScript, Go, Java, C# — same pattern everywhere.

> Status: alpha. The core workflows are usable today, but APIs, generated templates, and UX may still change as the project stabilizes.

![Kumi — one API for AI tool calling across languages and devices](assets/social-preview.png)

## Quick Start

```bash
pip install kumi-agent       # or, from source: git clone … && pip install .
kumi --server                # first run walks you through provider/model setup
kumi --demo                  # in another terminal: launches Smart Home + Planner
kumi --chat                  # ask AI to control them in natural language
```

Connect your own app:

```bash
cd my_project
kumi --edge --lang python    # also: typescript, swift, go, rust, kotlin, dart, java, csharp, cpp, ue5
```

`kumi --edge` scaffolds a `kumi_tools/` directory. Edit the generated setup file, call its init function from your app entry point, and your functions appear as AI tools. Full walkthrough in [Getting Started](docs/GETTING_STARTED.md).

## Demo

`kumi --demo` launches **two independent Python GUIs** at once:

- **Smart Home** — lights, TV, thermostat, coffee machine, locks (room cards + status)
- **Planner** — tkinter schedule app with a mini calendar and day timeline

Both windows are display-only. Open `kumi --chat` or `kumi --ui` and try:

> Turn on the kitchen lights and add a "Cook dinner" event at 18:00 for 1 hour, category personal.

The demo requires a graphical desktop session. On Linux, install Tk first (`sudo apt install python3-tk` on Debian/Ubuntu). More example prompts are in [Getting Started](docs/GETTING_STARTED.md#demo).

## Same pattern, every language

The flow is the same in every language: run `kumi --edge` → implement tools in any module you like → import them in the generated setup file, register them, and define `init_kumi` / `initKumi` → call that init function once from your app's entry point. There is no required folder layout; only the imports in setup need to reach your functions.

### Python

```python
# my_app/tools.py
def analyze_data(path: str) -> str:
    """Load a CSV and return a short summary."""
    return "summary"
```

```python
# kumi_tools/python/kumi_setup.py
from my_app.tools import analyze_data
from .kumi_sdk import KumiAgent

def init_kumi():
    agent = KumiAgent(edge_name="My Server")
    agent.register(analyze_data, "Analyze CSV at path and return a short summary")
    agent.run_in_background()
    return agent
```

```python
# your app entry point
from kumi_tools.python.kumi_setup import init_kumi
init_kumi()
# … rest of your program …
```

If you embed Kumi inside an already-installed Python package, `from kumi.sdk import KumiAgent` works directly without the `kumi_tools/` tree.

### TypeScript

```typescript
// kumi_tools/typescript/kumiSetup.ts
import { KumiAgent } from "./kumi_sdk/src";
import { searchProducts } from "../src/catalog";

export function initKumi() {
  const agent = new KumiAgent({ edgeName: "My Web App" });
  agent.register({
    name: "searchProducts",
    description: "Search the product catalog",
    handler: async (args) => searchProducts(args.string("query") ?? ""),
  });
  agent.runInBackground();
  return agent;
}
```

### Other languages

C++, Swift, Go, Java, C#, Rust, Kotlin, Dart, and UE5 follow the same pattern with idiomatic syntax. See the [Edge Tools Guide](docs/EDGE_TOOLS.md) for full code samples in each language.

## How It Works

```mermaid
flowchart TB
  subgraph ai [AI Brain]
    LLM[LLM Provider]
    Server[Kumi Server]
  end
  subgraph devices [Your Devices — Any Language]
    RPi["Raspberry Pi · C++"]
    Phone["iPhone · Swift"]
    Desktop["Desktop App · Python"]
    Web["Web App · TypeScript"]
    IoT["IoT Gateway · Go"]
  end
  LLM <--> Server
  Server <-->|WebSocket| RPi
  Server <-->|WebSocket| Phone
  Server <-->|WebSocket| Desktop
  Server <-->|WebSocket| Web
  Server <-->|WebSocket| IoT
```

Your app connects to the Kumi server over WebSocket and registers functions as tools. The LLM sees them alongside server-side tools and calls whichever it needs. Results flow back through the same connection.

## Main Commands

| Command | What it does |
|---|---|
| `kumi --server` | Start the backend API server |
| `kumi --server --telegram` | Start the API and a Telegram bot together (same machine) |
| `kumi --telegram` | Run only the Telegram bot; connects to the API like `kumi --chat` |
| `kumi --server --line` | Start the API and a LINE webhook sidecar (default port 8788) |
| `kumi --line` | Run only the LINE webhook server; core API must already be reachable |
| `kumi --server --voice` | Start the API with a microphone wake-word loop (say "hi kumi" to talk) |
| `kumi --ui` | Start the web UI (chat, tools, settings) |
| `kumi --chat` | Start terminal chat |
| `kumi --edge` | Scaffold an edge workspace in the current directory |
| `kumi --demo` | Run the Smart Home + Planner (schedule) demo |
| `kumi --setup` | Reconfigure models and providers |
| `kumi --config` | Create/update `~/.kumi/config.json` with all known settings and defaults |
| `kumi --cleanup` | Delete all Kumi user data (`~/.kumi/`) |
| `kumi --cleanup-memory` | Delete saved chat memory and embeddings only |

## Optional Integrations

- **Telegram** — chat with Kumi from a Telegram bot. Get a token from [@BotFather](https://t.me/BotFather), then run `kumi --server --telegram` (single machine) or `kumi --telegram` (bot only). Token, allowlist, and timer-push details: [Configuration → Telegram](docs/CONFIGURATION.md#telegram).
- **LINE** — chat from LINE via the Messaging API webhook. Run `kumi --server --line` (single machine, default port 8788) or `kumi --line` (webhook sidecar only). Credentials and webhook setup: [Configuration → LINE](docs/CONFIGURATION.md#line).
- **Voice** — talk to Kumi through your microphone. Say the wake word ("hi kumi") and Kumi transcribes the rest of your sentence with Whisper and runs it as a chat turn. Coexists with Telegram / `--chat` / `--ui` so the same Kumi instance can listen and type at once, and recent voice/Telegram/CLI turns are merged into each prompt. Requires `pip install kumi-agent[voice,stt]` plus a Picovoice access key. Setup: [Configuration → Voice](docs/CONFIGURATION.md#voice).

## Supported Providers

| Provider | Chat | Embedding | Notes |
|---|---|---|---|
| Ollama | Yes | Yes | Local models, no API key needed |
| OpenAI | Yes | Yes | Also works with OpenAI-compatible endpoints (point `openai_base_url` at DeepSeek, etc.) |
| Gemini | Yes | Yes | Google Gemini |
| Claude | Yes | No | Anthropic Claude (use another provider for embeddings) |
| DeepSeek | Yes | No | OpenAI-compatible chat API; use Ollama, OpenAI, Gemini, or Claude for embeddings |

You can mix providers — for example OpenAI for chat and Ollama for embeddings.

## Edge SDKs

| Language | Runtime | Install |
|---|---|---|
| Python | `websockets` | `pip install .` or `kumi --edge --lang python` |
| TypeScript | `ws` (Node) / native (browser) | `npm install kumi-sdk` or `kumi --edge --lang typescript` |
| C++ | CMake, IXWebSocket | `kumi --edge --lang cpp` |
| Swift | SwiftPM | `kumi --edge --lang swift` |
| Go | `gorilla/websocket` | `kumi --edge --lang go` |
| Java | JDK 11+ native WebSocket | `kumi --edge --lang java` |
| C# | .NET 6+ native WebSocket | `kumi --edge --lang csharp` |
| Rust | Tokio + `tokio-tungstenite` | `kumi --edge --lang rust` |
| Kotlin | OkHttp (JVM) | `kumi --edge --lang kotlin` |
| Dart | `web_socket_channel` (VM / Flutter) | `kumi --edge --lang dart` |
| UE5 | Unreal Engine module | `kumi --edge --lang ue5` |

## Documentation

| Document | Description |
|---|---|
| [Getting Started](docs/GETTING_STARTED.md) | Installation, first run, providers, UI, terminal chat |
| [Edge Tools Guide](docs/EDGE_TOOLS.md) | Connect your app, device, or game as an edge tool host |
| [Tool Registration](docs/TOOL_REGISTRATION.md) | All tool registration parameters, confirmation, proactive options |
| [Configuration](docs/CONFIGURATION.md) | `~/.kumi/config.json`, environment variables, Telegram, LINE, Docker |
| [Architecture](docs/ARCHITECTURE.md) | System design, plugin ports, API stability |
| [HTTP API](docs/HTTP_API.md) | Chat NDJSON stream, all routes, curl examples |
| [Memory](docs/MEMORY.md) | Session history and LanceDB embeddings |
| [Testing](docs/TESTING.md) | Running and writing tests |
| [Upgrading to Enterprise](docs/UPGRADING_TO_ENTERPRISE.md) | Switching to multi-tenant `kumi-enterprise` |

## How Kumi Differs

Kumi is **not** another Python-only LLM chaining library. It ships a runnable server, terminal UI, and web UI, plus **first-class edge tool hosts** across eleven languages. The focus is on **device-side tool execution**: your game, phone app, IoT sensor, or desktop program exposes functions, and the AI calls them directly in your process.

## OSS vs. Enterprise

This package (`kumi-agent`) is the **open-source single-user / LAN core**. It runs locally or on your home network, has no Bearer auth, no per-tenant scoping, and no quotas. Everything you need to chat with an agent and register tools across languages is here.

A separate **`kumi-enterprise`** package extends this core via the `kumi.core.plugins` port system to add multi-tenant identity, per-user encryption, billing/usage metering, an admin API, the public **relay** for remote pairing, and PostgreSQL-backed storage. It depends on this OSS package, registers itself via Python `entry_points` (group `kumi.plugins`), and ships its own CLI (`kumi-enterprise serve`). It is distributed privately and not on PyPI.

If you only need a personal or LAN agent, you do **not** need the enterprise package. When you do need multi-tenant identity, billing, relay, or PostgreSQL-backed storage, see [Upgrading to Enterprise](docs/UPGRADING_TO_ENTERPRISE.md).

## License

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).

[Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [Changelog](CHANGELOG.md) · [Commercial](COMMERCIAL.md) · [Code of Conduct](CODE_OF_CONDUCT.md)
