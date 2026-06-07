# Tool Registration Reference

Yumi tools are normal functions that the model may call. Good tool registration tells the model what the function does, what arguments it needs, whether it is safe to run automatically, and whether proactive messaging may use it.

Use this page for function/tool registration. Use [`CONFIGURATION.md`](CONFIGURATION.md) for project settings.

## Two Places To Register Tools

Server-local tools run inside the Yumi server process. They use `yumi.core.tool.register_tool(...)` and are best for built-in or trusted server functions.

Edge tools run inside your own app or device process. They connect to Yumi over WebSocket using an SDK such as Python, TypeScript, Go, Rust, Swift, Kotlin, Java, C#, C++, Dart, or UE5. This is the recommended path for app/device actions.

## Server-Local Registration

```python
from yumi.core.tool import register_tool


def get_weather(city: str) -> str:
    return f"Weather for {city}: light rain"


register_tool(
    get_weather,
    "Get the current weather for a city.",
    params={"city": "City name, for example Auckland"},
    returns="Short weather summary.",
)
```

Signature:

```python
register_tool(
    func,
    description=None,
    *,
    name=None,
    params=None,
    returns=None,
    allow_proactive=False,
    proactive_context=False,
    proactive_context_args=None,
    proactive_context_description=None,
) -> None
```

Parameters:

- `func`: Python callable to expose as a tool. It may be sync or async.
- `description`: Human-readable description shown to the model. This is one of the most important fields.
- `name`: Optional tool name override. Defaults to `func.__name__`.
- `params`: Optional mapping of argument name to description, for example `{"city": "City name"}`.
- `returns`: Optional return-value description appended to the tool description.
- `allow_proactive`: Allows proactive messaging to expose this tool to the model. Default: `false`.
- `proactive_context`: Calls this tool before proactive message generation and injects its result as read-only context. Default: `false`.
- `proactive_context_args`: Fixed arguments used for proactive context calls.
- `proactive_context_description`: Label shown when injecting proactive context, for example `Current weather`.

Type hints are converted into JSON schema. Supported common types include `str`, `int`, `float`, `bool`, `list`, `dict`, and simple optional types. Parameters without defaults are required.

## Python Edge SDK

```python
from yumi.sdk import YumiAgent

agent = YumiAgent(edge_name="Weather App")


def get_weather(city: str) -> str:
    return f"Weather for {city}: light rain"


agent.register(
    get_weather,
    "Get the current weather for a city.",
    params={"city": "City name"},
    timeout=20,
    allow_proactive=True,
    proactive_context=True,
    proactive_context_args={"city": "Auckland"},
    proactive_context_description="Current weather",
)

agent.run_in_background()
```

Common Python Edge options:

- `func`, `description`, `name`, `params`, `returns`: Same meaning as server-local registration.
- `timeout`: Optional per-tool execution timeout in seconds.
- `require_confirmation`: If `true`, the user must approve before the server invokes this Edge tool.
- `always_include`: If `true`, this Edge tool bypasses dynamic routing and is included every turn.
- `allow_proactive`: If `true`, proactive messaging may use this tool.
- `proactive_context`: If `true`, proactive messaging calls this tool before generation and injects the result.
- `proactive_context_args`: Fixed arguments for proactive context calls.
- `proactive_context_description`: Label for the injected proactive context result.

The shortcut API in `yumi/__init__.py` mirrors the Python Edge SDK:

```python
import yumi

yumi.register(get_weather, "Get weather", allow_proactive=True)
yumi.run(edge_name="Weather App")
```

## Other Edge SDKs

All Edge SDKs use the same wire-level metadata even if naming follows each language's style.

Universal fields:

- `name`: Tool name shown to the model.
- `description`: What the tool does and when to use it.
- `parameters`: JSON-schema-style parameter descriptors.
- `handler`: Function/closure called when Yumi invokes the tool.
- `timeout`: Optional timeout in seconds, where supported.
- `requireConfirmation` / `require_confirmation` / `RequireConfirmation`: Require user approval.
- `alwaysInclude` / `always_include` / `AlwaysInclude`: Always expose this Edge tool to the model.
- `allowProactive` / `allow_proactive` / `AllowProactive`: Allow proactive messaging to use this tool.
- `proactiveContext` / `proactive_context` / `ProactiveContext`: Force-call before proactive generation as context.
- `proactiveContextArgs` / `proactive_context_args` / `ProactiveContextArgs`: Fixed args for proactive context.
- `proactiveContextDescription` / `proactive_context_description` / `ProactiveContextDescription`: Label for proactive context.

Example TypeScript:

```typescript
agent.register({
  name: "get_weather",
  description: "Get current weather for a city.",
  parameters: [{ name: "city", type: "string", description: "City name" }],
  allowProactive: true,
  proactiveContext: true,
  proactiveContextArgs: { city: "Auckland" },
  proactiveContextDescription: "Current weather",
  handler: async (args) => getWeather(String(args.city)),
});
```

Example Go:

```go
agent.Register(yumi.RegisterOptions{
    Name:        "get_weather",
    Description: "Get current weather for a city.",
    AllowProactive: true,
    ProactiveContext: true,
    ProactiveContextArgs: map[string]interface{}{"city": "Auckland"},
    ProactiveContextDescription: "Current weather",
    Handler: func(args yumi.ToolArguments) string {
        return getWeather(args.String("city"))
    },
})
```

## Safety Rules

Use `require_confirmation=True` for irreversible or sensitive actions, such as deleting files, sending money, placing orders, unlocking doors, or changing device state in a risky way.

Do not mark side-effect tools as proactive. Proactive messaging is unattended, so `allow_proactive` and `proactive_context` should be limited to safe read-only tools such as time, weather, calendar summaries, study progress, or status checks.

Tools with `require_confirmation=True` are filtered out of proactive execution, even if they also set `allow_proactive=True`.

## Writing Good Tool Descriptions

Prefer concrete descriptions:

```text
Good: Get today's calendar events for the user.
Weak: Calendar tool.
```

Describe units, limits, and side effects in the description or parameter descriptions. The model decides whether to call a tool largely from this text.

Keep parameter names stable. Renaming a tool or argument changes what the model sees and may break existing prompts or Edge clients.

## Related Docs

- [`EDGE_TOOLS.md`](EDGE_TOOLS.md): Edge setup, connection, routing, and SDK overview.
- [`CONFIGURATION.md`](CONFIGURATION.md): `~/.yumi/config.json` and environment variables.
