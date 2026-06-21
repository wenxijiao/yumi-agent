# Edge Tools Guide

Edge tools let the LLM call functions inside your own app or device process. Your app connects to the Yumi server over WebSocket, registers functions as tools, and the AI invokes them as needed.

Yumi loads core server tools on every turn, but Edge tools are dynamically routed by default. All tools registered by connected Edge processes stay in the server registry; for each chat turn Yumi uses the configured embedding model to select the most relevant Edge tool schemas (default: 20) before calling the LLM.

For the full parameter reference for `register(...)`, `RegisterOptions`, confirmation, and proactive tool metadata, see [`TOOL_REGISTRATION.md`](TOOL_REGISTRATION.md).

## Quick Start

```bash
cd my_project
yumi --edge
```

Or scaffold a subset of languages (repeat `--lang` or use commas):

```bash
yumi --edge --lang python
yumi --edge --lang rust --lang python
yumi --edge --lang rust,python
yumi --edge --lang swift
yumi --edge --lang typescript
yumi --edge --lang cpp
yumi --edge --lang ue5
yumi --edge --lang go
yumi --edge --lang java
yumi --edge --lang csharp
yumi --edge --lang rust
yumi --edge --lang kotlin
yumi --edge --lang dart
```

This creates `yumi_tools/`, a `.env` file, and language-specific setup templates.

## Next Steps After `yumi --edge`

1. Open `yumi_tools/README.md`
2. Open the README for your language
3. Edit the generated setup file
4. Call the generated initialization function from your real app entry point

`yumi --edge` only scaffolds files. Your own app still needs to call the generated `init_*` / `Init*` function at runtime.

## Tool Routing

Use meaningful Edge names when possible. Names like `Bedroom`, `Memory App`, or `Game NPC` become part of each Edge tool's retrieval document, so a request like "turn on the bedroom light" will prefer light-related tools registered under the bedroom Edge. If the Edge name is generic (for example `device-001`), Yumi still falls back to the function name, description, and parameter descriptions, so good tool descriptions remain important.

When an Edge reconnects, updates, or removes tools, the next chat turn uses the current in-memory registry. There is no persistent per-tool routing file to clean up; embedding vectors are cached in memory only and old deleted tools are no longer referenced.

For an Edge function that must be available to the model on every turn, register it with `always_include=True` (or the SDK equivalent such as `alwaysInclude: true`). This is off by default and should be reserved for small, high-value tools because it bypasses dynamic Edge-tool retrieval for that function.

Configure the per-turn Edge tool budget with:

```bash
yumi --tool-routing --edge-tools-limit 30
```

Or via HTTP:

```bash
curl -X PUT "$YUMI_SERVER_URL/config/model" \
  -H "Content-Type: application/json" \
  -d '{"edge_tools_enable_dynamic_routing":true,"edge_tools_retrieval_limit":30}'
```

## SDK Overview

Every SDK follows the same core model:

1. Create a `YumiAgent`
2. Register tools
3. Start the agent in the background
4. Let your main app continue running normally

### Python

```python
from yumi.sdk import YumiAgent

agent = YumiAgent(edge_name="My Device")
agent.register(my_function, "What this function does")
agent.run_in_background()
```

Runtime dependency: `websockets`

### TypeScript

```typescript
import { YumiAgent } from "yumi-sdk";

const agent = new YumiAgent({ edgeName: "My Web App" });
agent.register({
  name: "my_function",
  description: "What this function does",
  handler: async (args) => myFunction(args),
});
agent.runInBackground();
```

Runtime dependency in Node: `ws`. Browser uses native `WebSocket`.

### C++

```cpp
#include <yumi/yumi_agent.hpp>

yumi::YumiAgent agent("yumi-lan_...", "My Device");
agent.registerTool({
    .name = "my_function",
    .description = "What this function does",
    .handler = [](auto args) { return myFunction(args); }
});
agent.runInBackground();
```

Build with CMake. Uses IXWebSocket when available.

### Swift

```swift
import YumiSDK

let agent = YumiAgent(edgeName: "My iPhone")
agent.register(
    name: "my_function",
    description: "What this function does"
) { args in
    return myFunction(args)
}
agent.runInBackground()
```

Uses SwiftPM. Full package copied into edge workspace.

### Go

```go
agent := yumi_sdk.NewAgent(yumi_sdk.AgentOptions{
    EdgeName: "My Go Service",
})
agent.Register(yumi_sdk.RegisterOptions{
    Name:        "my_function",
    Description: "What this function does",
    Handler:     func(args yumi_sdk.ToolArguments) (string, error) {
        return myFunction(args)
    },
})
agent.RunInBackground()
```

Runtime dependency: `gorilla/websocket`

### Java

```java
var agent = new YumiAgent("yumi-lan_...", "My Java App");
agent.register(new RegisterOptions()
    .name("my_function")
    .description("What this function does")
    .handler(args -> myFunction(args)));
agent.runInBackground();
```

JDK 11+ native WebSocket. Only external dependency: Gson.

### Rust

```rust
use yumi_sdk::{AgentOptions, YumiAgent, RegisterOptions, ToolParameter};
use std::sync::Arc;

let agent = YumiAgent::new(AgentOptions {
    connection_code: None,
    edge_name: Some("My Rust App".into()),
    env_path: None,
});
agent.register(RegisterOptions {
    name: "my_function".into(),
    description: "What this function does".into(),
    parameters: vec![],
    timeout: None,
    require_confirmation: false,
    always_include: false,
    handler: Arc::new(|args| args.string("q")),
});
agent.run_in_background();
```

Runtime: Tokio + `tokio-tungstenite`. Call `init_yumi()` from `#[tokio::main] async fn main()`.

### Kotlin (JVM)

```kotlin
val agent = YumiAgent(AgentOptions(edgeName = "My Kotlin App"))
agent.register(
    RegisterOptions(
        name = "my_function",
        description = "What this function does",
        handler = ToolHandler { args -> "ok" },
    ),
)
agent.runInBackground()
```

OkHttp WebSocket + Gson. Sources live under `io.yumi.sdk` in the edge workspace.

### Dart (VM)

```dart
final agent = YumiAgent(AgentOptions(edgeName: 'My Dart App'));
agent.register(RegisterOptions(
  name: 'my_function',
  description: 'What this function does',
  handler: (args) => 'ok',
));
agent.runInBackground();
```

`web_socket_channel` + `http`. Suitable for CLI/server; Flutter can use the same `yumi_sdk` package.

### UE5

Native Unreal Engine 5 module. See [`yumi/sdk/ue5/`](../yumi/sdk/ue5/) for source.

## Connection

### Connection Resolution

Connection resolution is the same across all SDKs:

1. Explicit connection code passed to the SDK
2. `YUMI_CONNECTION_CODE` env var
3. Legacy `BRAIN_URL` env var (where supported)
4. Local fallback: `ws://127.0.0.1:8000/ws/edge`

### Connection Code Formats

| Format | Example |
|---|---|
| LAN code | `yumi-lan_...` |
| WebSocket URL | `ws://192.168.1.10:8000/ws/edge` |
| HTTP URL | `http://192.168.1.10:8000` |

> **A LAN code is a connection string, not a credential.** It just encodes the
> server host/port (so the SDK knows where to connect). The OSS server has no
> auth, so reaching the host/port is what grants access — anyone on the network
> who can connect, can register tools. The optional `lan_secret` HMAC only
> detects tampering, and only when both ends share the secret; it does not
> authenticate the client. Don't expose the server on an untrusted network
> (the default bind is loopback-only — see [Configuration](CONFIGURATION.md));
> per-user identity/auth is a higher-layer (L2) concern.

## Tool Confirmation

Set `require_confirmation=True` (Python) or the equivalent flag in other SDKs for tools with irreversible side effects. The user must approve in the Yumi UI or terminal chat before the tool is invoked.

Tool confirmation policy is persisted to disk when the platform supports it. Browser-based TypeScript keeps it in memory.

## Proactive Messaging Tool Opt-In

Proactive messaging never uses tools by default. Read-only tools can opt in with `allow_proactive=True` (or the equivalent SDK flag). Tools can also set `proactive_context=True` plus optional fixed `proactive_context_args` so Yumi calls them before generating a proactive message and injects the result as background context.

Do not enable proactive access for tools with side effects. Tools that require confirmation are filtered out of unattended proactive runs.

## `yumi --edge` Mapping

| Command | Generated result |
|---|---|
| `yumi --edge` | All language templates + SDK copies |
| `yumi --edge --lang python` | Python template + Python SDK copy |
| `yumi --edge --lang swift` | Swift template + full Swift package |
| `yumi --edge --lang typescript` | TS template + SDK tree |
| `yumi --edge --lang cpp` | C/C++ template + CMake tree |
| `yumi --edge --lang ue5` | UE5 template + module source |
| `yumi --edge --lang go` | Go template + local module source |
| `yumi --edge --lang java` | Java template + Maven project |
| `yumi --edge --lang csharp` | C# template + .NET project |
| `yumi --edge --lang rust` | Rust template + `yumi_sdk` crate |
| `yumi --edge --lang kotlin` | Kotlin template + `io.yumi.sdk` sources |
| `yumi --edge --lang dart` | Dart template + `yumi_sdk` package |

## Further Reading

- SDK source and maintainer notes: [`yumi/sdk/README.md`](../yumi/sdk/README.md)
- Edge workspace template: [`yumi/edge/template/yumi_tools/README.md`](../yumi/edge/template/yumi_tools/README.md)
