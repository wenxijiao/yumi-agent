# Kumi Edge Agent Guide

This file is written for coding agents working inside a project that was
generated with `kumi --edge`. The Kumi source tree is often not available in
that project, so this guide explains how to use the generated SDK scaffold
without reading Kumi internals.

Canonical source: `kumi/sdk/AGENTS.md` in the `kumi-agent` package. When
`kumi --edge` runs, Kumi copies this file to the edge project root as
`AGENTS.md`.

## Mental Model

Kumi has two processes:

- The Kumi server runs the LLM, chat API, memory, tool routing, and UI.
- The edge project runs inside the user's app, game, service, or device and
  exposes local functions to the Kumi server over WebSocket.

Do not import Kumi server internals from an edge project. Edge code should use
only the generated SDK for its language and the app's own code. The server will
call registered edge tools when the model decides they are relevant.

An edge tool is just a normal function plus metadata:

- `name`: stable tool name shown to the model.
- `description`: when and why the model should call it.
- `parameters`: JSON-schema-style parameter definitions.
- `handler`: function or closure that executes in the edge process.
- optional safety and routing flags such as confirmation, timeout, proactive
  access, and always-include.

## Generated Workspace Layout

`kumi --edge` creates files like this:

```text
project-root/
|-- AGENTS.md                 # this guide, for coding agents
|-- .gitignore                # generated only if missing
`-- kumi_tools/
    |-- .env                  # connection code and edge name
    |-- README.md             # generated workspace overview
    |-- python/
    |-- swift/
    |-- typescript/
    |-- cpp/
    |-- ue5/
    |-- go/
    |-- java/
    |-- csharp/
    |-- rust/
    |-- kotlin/
    `-- dart/
```

If `kumi --edge --lang python` or another `--lang` subset was used, only the
selected language folders are present.

Each language folder has:

- a setup file that you edit to register tools and start the client
- a local SDK copy that you usually do not edit
- a language-specific `README.md`

Prefer editing the setup file and the host app code. Treat the generated SDK
copy as vendored runtime code unless the user explicitly asks you to modify or
debug the SDK itself.

## First Steps For A Coding Agent

1. Inspect `kumi_tools/README.md`.
2. Pick the language folder that matches the host app.
3. Read that language folder's `README.md`.
4. Edit the generated setup file for that language.
5. Wire the setup function into the real app entry point.
6. Keep the app process alive; the edge client runs in the background for most
   SDKs.

Do not add server-local Kumi tools from an edge project. Server-local tools use
`kumi.core.tool.register_tool(...)` and belong inside the Kumi server package.
Generated edge projects should use the edge SDK registration API.

## Connection Configuration

Most generated SDKs read connection settings in this order:

1. `KUMI_RELAY_URL` plus `KUMI_ACCESS_TOKEN`
2. explicit connection code passed in code
3. `KUMI_CONNECTION_CODE`
4. legacy `BRAIN_URL` where supported
5. local fallback such as `ws://127.0.0.1:8000/ws/edge`

The generated `.env` lives at:

```text
kumi_tools/.env
```

Common values:

```env
KUMI_CONNECTION_CODE=kumi-lan_...
EDGE_NAME=My App
```

Accepted connection-code shapes:

- `kumi-lan_...` for LAN pairing
- `kumi_...` for relay pairing
- `ws://...` or `wss://...`
- `http://...` or `https://...`

For browser TypeScript, do not rely on reading `.env` at runtime. Pass
`connectionCode` and `edgeName` to `new KumiAgent(...)`, or inject them at
build time.

## Tool Design Rules

Good tool metadata matters more than clever code. The LLM chooses tools based
on names, descriptions, parameter descriptions, and the edge name.

Use:

- stable snake_case or language-idiomatic tool names
- concrete descriptions with units, limits, and side effects
- explicit parameter descriptions
- narrow tools that map to one app capability
- clear return strings or JSON-serializable summaries

Avoid:

- vague descriptions such as "Do app action"
- renaming tools casually after users rely on them
- hidden side effects that are not described
- long blocking handlers when the SDK or runtime can support async work
- putting secrets in tool descriptions or return values

Use `require_confirmation`, `requireConfirmation`, or the language equivalent
for actions that are irreversible, expensive, external, or sensitive: deleting
data, sending messages, placing orders, moving money, unlocking doors, changing
security settings, or destructive game and editor actions.

Use `always_include` or `alwaysInclude` sparingly. It bypasses dynamic
edge-tool routing and exposes the tool schema every turn. Reserve it for tiny,
high-value tools that must always be visible.

Use proactive flags only for safe read-only tools. Proactive messaging is
unattended. Do not mark side-effect tools as proactive.

## Dynamic Edge Tool Routing

Kumi does not necessarily send every connected edge tool to the model on every
turn. Edge tools are dynamically routed by default. The server keeps the
registered tool catalog in memory and selects the most relevant edge schemas for
each chat turn.

Implications for edge projects:

- Choose meaningful `EDGE_NAME` values such as `Bedroom`, `Game NPC`, or
  `Calendar App`.
- Make tool and parameter descriptions specific enough for retrieval.
- Use `always_include` only when retrieval would be harmful or confusing.
- If a tool was just added and the server is connected, the next chat turn can
  use the updated registry.

## Language Entry Points

### Python

Edit:

```text
kumi_tools/python/kumi_setup.py
```

Typical pattern:

```python
from .kumi_sdk import KumiAgent
from my_app.actions import jump


def init_kumi():
    agent = KumiAgent(edge_name="My Python App")
    agent.register(jump, "Make the character jump.")
    agent.run_in_background()
    return agent
```

Call from the real app:

```python
from kumi_tools.python.kumi_setup import init_kumi

kumi_agent = init_kumi()
```

For a smoke test:

```bash
python -m kumi_tools.python.kumi_setup
```

The Python SDK can infer JSON schema from type hints. Add type hints and
docstring `Args:` sections, or pass `params={...}` explicitly.

### TypeScript / JavaScript

Edit:

```text
kumi_tools/typescript/kumiSetup.ts
```

Install SDK dependencies:

```bash
cd kumi_tools/typescript/kumi_sdk
npm install
```

Typical pattern:

```ts
import { KumiAgent } from "./kumi_sdk/src";

export function initKumi() {
  const agent = new KumiAgent({ edgeName: "My Web App" });
  agent.register({
    name: "set_light",
    description: "Control room lights.",
    parameters: [
      { name: "room", type: "string", description: "Room name" },
      { name: "on", type: "boolean", description: "Turn on or off" },
    ],
    handler: async (args) => {
      const room = args.string("room") ?? "living_room";
      const on = args.bool("on") ?? false;
      return `Light in ${room}: ${on}`;
    },
  });
  agent.runInBackground();
  return agent;
}
```

For a Node smoke test:

```bash
cd kumi_tools/typescript
npx tsx kumiSetup.ts
```

In browser apps, import the SDK through the app's bundler and pass connection
configuration in code or build-time config.

### Go

Edit:

```text
kumi_tools/go/kumi_setup.go
```

In the host app's `go.mod`:

```text
require kumi_sdk v0.0.0
replace kumi_sdk => ./kumi_tools/go/kumi_sdk
```

Call `InitKumi()` from the real `main`. The generated `main.go` is only a
standalone smoke-test entry and can be removed when embedding.

### Rust

Edit:

```text
kumi_tools/rust/src/kumi_setup.rs
```

Point the host crate at the generated SDK:

```toml
kumi_sdk = { path = "kumi_tools/rust/kumi_sdk" }
```

Use Tokio and call the generated init function from an async main where
appropriate. The generated Rust folder can also be run directly with:

```bash
cd kumi_tools/rust
cargo run
```

### Swift

Edit:

```text
kumi_tools/swift/KumiSetup.swift
```

Add `kumi_tools/swift/KumiSDK` as a local Swift package in Xcode, or add the
SDK sources to the same target. Call `initKumi()` early in app startup, such as
from `App.init`, an app delegate, or a command-line entry point. For Apple apps,
literal connection configuration in `KumiSetup.swift` is usually less
surprising than runtime `.env` discovery.

### C / C++

Edit:

```text
kumi_tools/cpp/kumi_setup.cpp
```

Add the SDK to CMake:

```cmake
add_subdirectory(kumi_tools/cpp/KumiSDK)
target_link_libraries(your_app PRIVATE kumi_sdk)
```

Use `kumi::KumiAgent` for C++. Use the C ABI in
`KumiSDK/include/kumi/kumi_agent.h` only when doing C or FFI integration.

### Unreal Engine 5

Edit:

```text
kumi_tools/ue5/KumiSetup.h
kumi_tools/ue5/KumiSetup.cpp
```

Copy or reference the generated `KumiSDK` module from the UE project, add
`KumiSDK` to the game's `.Build.cs`, and call `InitKumi()` from an early game
lifecycle hook such as `UGameInstance::Init()`.

### Java

Edit:

```text
kumi_tools/java/KumiSetup.java
```

Use the generated `kumi_sdk` Maven project as a module, install it locally, or
copy its sources into the host app. Call `KumiSetup.initKumi()` from the host
app's `main`. The generated `KumiEdgeMain.java` is a smoke-test entry and can
be removed when embedding.

### C#

Edit:

```text
kumi_tools/csharp/KumiSetup.cs
```

Reference the generated SDK project:

```xml
<ItemGroup>
  <ProjectReference Include="kumi_tools/csharp/kumi_sdk/KumiSDK.csproj" />
</ItemGroup>
```

Call `KumiSetup.InitKumi()` from the host app's entry point. Dispose or stop
the returned agent during shutdown when the host app has a clean lifecycle.

### Kotlin

Edit:

```text
kumi_tools/kotlin/src/main/kotlin/io/kumi/edge/KumiSetup.kt
```

The SDK sources are copied into:

```text
kumi_tools/kotlin/src/main/kotlin/io/kumi/sdk/
```

Run the generated project with Gradle for a smoke test, then call the generated
setup function from the host JVM app.

### Dart

Edit:

```text
kumi_tools/dart/lib/kumi_setup.dart
```

The generated SDK package lives at:

```text
kumi_tools/dart/kumi_sdk/
```

Run a smoke test with:

```bash
cd kumi_tools/dart
dart pub get
dart run
```

For Flutter, wire the generated `kumi_sdk` package into the app and call the
setup function from app startup.

## Registration Field Reference

Field names vary slightly by language, but the contract is the same.

| Concept | Common names | Meaning |
|---|---|---|
| Tool name | `name`, `Name` | Stable name shown to the model |
| Description | `description`, `Description` | Primary LLM-facing usage instruction |
| Parameters | `parameters`, `Parameters`, `params` | JSON-schema-style arguments |
| Handler | `handler`, `Handler` | Code called when Kumi invokes the tool |
| Timeout | `timeout`, `Timeout` | Per-tool execution timeout in seconds |
| Confirmation | `require_confirmation`, `requireConfirmation`, `RequireConfirmation` | Ask user before invocation |
| Always include | `always_include`, `alwaysInclude`, `AlwaysInclude` | Always expose schema to model |
| Proactive use | `allow_proactive`, `allowProactive`, `AllowProactive` | Permit unattended proactive calls |
| Proactive context | `proactive_context`, `proactiveContext`, `ProactiveContext` | Call read-only tool before proactive generation |

Supported primitive parameter types are generally:

- `string`
- `integer`
- `number`
- `boolean`
- `array`
- `object`

Use language-specific helper classes such as `ToolParameter` where provided.

## Lifecycle And Concurrency

Most SDKs have a background-run method such as `run_in_background()`,
`runInBackground()`, or `RunInBackground()`. Call it once during app startup
after registering tools.

The edge process must remain alive. If the host process exits, the server loses
the edge connection and the tools become unavailable.

Reconnects are automatic in the SDKs. On reconnect, the SDK sends the current
tool registry again. If you add conditional registration, make sure all expected
tools are registered before the connection starts or before reconnect happens.

Handler cancellation differs by runtime. Async handlers can often be cancelled
at await points. Synchronous handlers may continue running even if the server
times out. Keep dangerous operations short, cancellable where possible, and
behind confirmation.

## Testing Checklist

After changing edge integration, run the smallest meaningful check:

- Make sure the Kumi server is running: `kumi --server`
- Generate or refresh scaffolding if needed: `kumi --edge --lang <lang>`
- Set `kumi_tools/.env`
- Run the language-specific smoke test from that language's README
- Confirm the edge appears in the Kumi UI or `/monitor`
- Ask the model to call one harmless tool
- Test a confirmation-required tool if you added one

Examples:

```bash
python -m kumi_tools.python.kumi_setup
```

```bash
cd kumi_tools/typescript && npx tsx kumiSetup.ts
```

```bash
cd kumi_tools/go && go run .
```

```bash
cd kumi_tools/rust && cargo run
```

## Troubleshooting

If the edge does not show up:

- Check that the host app actually calls the generated init function.
- Check `kumi_tools/.env` and `KUMI_CONNECTION_CODE`.
- Start the Kumi server first with `kumi --server`.
- For LAN pairing, make sure the edge device can reach the server host and
  port.
- For browser TypeScript, pass connection config in code instead of expecting
  `.env`.
- Look for WebSocket or authentication errors in the edge process logs.

If the model does not call a tool:

- Improve the tool description and parameter descriptions.
- Use a more meaningful `EDGE_NAME`.
- Ask with wording that matches the tool's purpose.
- Check whether dynamic routing is hiding the tool.
- Consider `always_include` only for critical, low-volume tools.

If a tool call fails:

- Validate argument names and types.
- Return strings or JSON-serializable values.
- Catch app-specific exceptions and return concise error messages.
- Add confirmation for sensitive tools instead of silently refusing.

## What Not To Do

- Do not import `kumi.core.*` from generated edge projects.
- Do not edit vendored SDK copies unless the task is explicitly SDK work.
- Do not delete language folders just because they are unused unless the user
  asks for cleanup.
- Do not put secrets in tool descriptions, generated logs, or return values.
- Do not mark side-effect tools as proactive.
- Do not bypass confirmation for irreversible or externally visible actions.
- Do not assume every edge tool is sent to the model every turn.

## Where To Look Next

Inside a generated edge project:

- `AGENTS.md`: this guide
- `kumi_tools/README.md`: generated workspace overview
- `kumi_tools/<lang>/README.md`: language-specific setup
- `kumi_tools/<lang>/*setup*`: file to edit for tool registration
- `kumi_tools/.env`: connection settings

Inside the `kumi-agent` source tree, if available:

- `docs/EDGE_TOOLS.md`: full edge guide
- `docs/TOOL_REGISTRATION.md`: registration flags and safety reference
- `kumi/sdk/README.md`: maintainer-facing SDK source layout
- `kumi/sdk/AGENTS.md`: canonical version of this file
