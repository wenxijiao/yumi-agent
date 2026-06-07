# Kumi SDKs

This directory holds the **canonical source** for every Kumi edge SDK. `kumi --edge` copies SDK code out of this directory into a self-contained `kumi_tools/` workspace inside the user's project.

> Looking for usage examples? See [`docs/EDGE_TOOLS.md`](../../docs/EDGE_TOOLS.md) for full code samples in each language. This file is the **maintainer-facing** layout overview.

For coding agents working in generated edge projects, [`AGENTS.md`](AGENTS.md)
is the canonical SDK guide. `kumi --edge` copies it to the generated project
root so agents can understand the SDK without access to this source tree.

## Who This Is For

- **Kumi users** integrating edge tools: start from `kumi --edge` and then open `kumi_tools/<lang>/README.md`, or read [`docs/EDGE_TOOLS.md`](../../docs/EDGE_TOOLS.md).
- **SDK maintainers**: this directory is the canonical implementation — update SDK logic here first, then let `kumi --edge` copy it into user projects.

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
| Python | `pip`, `websockets` | `kumi.sdk.KumiAgent` | self-contained single-file runtime |
| Swift | SwiftPM / Xcode | `KumiAgent` | full package copied into edge workspace |
| TypeScript / JavaScript | npm | `KumiAgent` | isomorphic: browser + Node |
| C / C++ | CMake | `kumi::KumiAgent` | header-only C++ core + optional C ABI |
| UE5 | UE module | `FKumiAgent` | native UE5 implementation; **CI does not compile UE5** (requires a local Unreal toolchain) |
| Go | Go modules | `kumi_sdk.NewAgent` | local-module workflow via `replace` |
| Java | Maven | `new KumiAgent(...)` | JDK 11+ native WebSocket; only external dep is Gson |
| C# | .NET 6+ | `new KumiAgent(...)` | native `System.Net.WebSockets`, zero external deps |
| Rust | Cargo, Tokio | `KumiAgent::new` | `tokio-tungstenite`, relay bootstrap via `reqwest` |
| Kotlin | JVM, Gradle | `KumiAgent(...)` | OkHttp WebSocket + Gson |
| Dart | `dart pub`, VM / Flutter | `KumiAgent(...)` | `web_socket_channel` + `http` |

## Edge Workspace Targets

When `kumi --edge` runs, code from this tree is copied into the user's project as follows:

| SDK | Edge workspace target |
|---|---|
| Python | `kumi_tools/python/kumi_sdk/` |
| TypeScript | `kumi_tools/typescript/kumi_sdk/` |
| C++ | `kumi_tools/cpp/KumiSDK/` |
| Swift | `kumi_tools/swift/KumiSDK/` |
| Go | `kumi_tools/go/kumi_sdk/` (consumed via `replace` in `go.mod`) |
| Java | `kumi_tools/java/kumi_sdk/` |
| C# | `kumi_tools/csharp/kumi_sdk/` |
| Rust | `kumi_tools/rust/kumi_sdk/` |
| Kotlin | `kumi_tools/kotlin/kumi_sdk/` |
| Dart | `kumi_tools/dart/kumi_sdk/` |
| UE5 | `kumi_tools/ue5/KumiSDK/` |

## Connection Resolution (Cross-SDK Contract)

Every SDK resolves the connection in the same order:

1. `KUMI_RELAY_URL` + `KUMI_ACCESS_TOKEN`
2. Explicit connection code passed to the SDK
3. `KUMI_CONNECTION_CODE`
4. Legacy `BRAIN_URL` (where supported)
5. Local fallback such as `ws://127.0.0.1:8000/ws/edge`

Accepted connection-code shapes: `kumi-lan_…` (LAN), `kumi_…` (relay pairing), `ws://…` / `wss://…`, `http://…` / `https://…`.

Tool confirmation policy is persisted to local disk where the host platform allows it; browser-based TypeScript keeps it in memory.

## Where To Go Next

- End-user docs: [`docs/EDGE_TOOLS.md`](../../docs/EDGE_TOOLS.md), [`docs/TOOL_REGISTRATION.md`](../../docs/TOOL_REGISTRATION.md)
- Edge workspace template: [`kumi/edge/template/kumi_tools/README.md`](../edge/template/kumi_tools/README.md)
