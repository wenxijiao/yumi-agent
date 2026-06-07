# Yumi SDKs

This directory holds the **canonical source** for every Yumi edge SDK. `yumi --edge` copies SDK code out of this directory into a self-contained `yumi_tools/` workspace inside the user's project.

> Looking for usage examples? See [`docs/EDGE_TOOLS.md`](../../docs/EDGE_TOOLS.md) for full code samples in each language. This file is the **maintainer-facing** layout overview.

For coding agents working in generated edge projects, [`AGENTS.md`](AGENTS.md)
is the canonical SDK guide. `yumi --edge` copies it to the generated project
root so agents can understand the SDK without access to this source tree.

## Who This Is For

- **Yumi users** integrating edge tools: start from `yumi --edge` and then open `yumi_tools/<lang>/README.md`, or read [`docs/EDGE_TOOLS.md`](../../docs/EDGE_TOOLS.md).
- **SDK maintainers**: this directory is the canonical implementation — update SDK logic here first, then let `yumi --edge` copy it into user projects.

## Layout

```text
sdk/
├── README.md
├── AGENTS.md
├── __init__.py
├── python/
├── swift/
├── typescript/
├── cpp/
├── ue5/
├── go/
├── java/
├── csharp/
├── rust/
├── kotlin/
└── dart/
```

## Language Overview

| Language | Runtime / build | Main entry | Notes |
|---|---|---|---|
| Python | `pip`, `websockets` | `yumi.sdk.YumiAgent` | self-contained single-file runtime |
| Swift | SwiftPM / Xcode | `YumiAgent` | full package copied into edge workspace |
| TypeScript / JavaScript | npm | `YumiAgent` | isomorphic: browser + Node |
| C / C++ | CMake | `yumi::YumiAgent` | header-only C++ core + optional C ABI |
| UE5 | UE module | `FYumiAgent` | native UE5 implementation; **CI does not compile UE5** (requires a local Unreal toolchain) |
| Go | Go modules | `yumi_sdk.NewAgent` | local-module workflow via `replace` |
| Java | Maven | `new YumiAgent(...)` | JDK 11+ native WebSocket; only external dep is Gson |
| C# | .NET 6+ | `new YumiAgent(...)` | native `System.Net.WebSockets`, zero external deps |
| Rust | Cargo, Tokio | `YumiAgent::new` | `tokio-tungstenite`, relay bootstrap via `reqwest` |
| Kotlin | JVM, Gradle | `YumiAgent(...)` | OkHttp WebSocket + Gson |
| Dart | `dart pub`, VM / Flutter | `YumiAgent(...)` | `web_socket_channel` + `http` |

## Edge Workspace Targets

When `yumi --edge` runs, code from this tree is copied into the user's project as follows:

| SDK | Edge workspace target |
|---|---|
| Python | `yumi_tools/python/yumi_sdk/` |
| TypeScript | `yumi_tools/typescript/yumi_sdk/` |
| C++ | `yumi_tools/cpp/YumiSDK/` |
| Swift | `yumi_tools/swift/YumiSDK/` |
| Go | `yumi_tools/go/yumi_sdk/` (consumed via `replace` in `go.mod`) |
| Java | `yumi_tools/java/yumi_sdk/` |
| C# | `yumi_tools/csharp/yumi_sdk/` |
| Rust | `yumi_tools/rust/yumi_sdk/` |
| Kotlin | `yumi_tools/kotlin/yumi_sdk/` |
| Dart | `yumi_tools/dart/yumi_sdk/` |
| UE5 | `yumi_tools/ue5/YumiSDK/` |

## Connection Resolution (Cross-SDK Contract)

Every SDK resolves the connection in the same order:

1. `YUMI_RELAY_URL` + `YUMI_ACCESS_TOKEN`
2. Explicit connection code passed to the SDK
3. `YUMI_CONNECTION_CODE`
4. Legacy `BRAIN_URL` (where supported)
5. Local fallback such as `ws://127.0.0.1:8000/ws/edge`

Accepted connection-code shapes: `yumi-lan_…` (LAN), `yumi_…` (relay pairing), `ws://…` / `wss://…`, `http://…` / `https://…`.

Tool confirmation policy is persisted to local disk where the host platform allows it; browser-based TypeScript keeps it in memory.

## Where To Go Next

- End-user docs: [`docs/EDGE_TOOLS.md`](../../docs/EDGE_TOOLS.md), [`docs/TOOL_REGISTRATION.md`](../../docs/TOOL_REGISTRATION.md)
- Edge workspace template: [`yumi/edge/template/yumi_tools/README.md`](../edge/template/yumi_tools/README.md)
