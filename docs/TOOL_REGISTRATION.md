# Tool Registration Reference

Yumi tools are normal functions that the model may call, expose every turn, or run automatically as context. Good tool registration tells the model what the function does, what arguments it needs, whether it is safe to run automatically, and whether proactive messaging may use it.

Use this page for function/tool registration. Use [`CONFIGURATION.md`](CONFIGURATION.md) for project settings.

## Two Places To Register Tools

Server-local tools run inside the Yumi server process. They use `yumi.core.platform.tools.tool.register_tool(...)` and are best for built-in or trusted server functions.

Edge tools run inside your own app or device process. They connect to Yumi over WebSocket using an SDK such as Python, TypeScript, Go, Rust, Swift, Kotlin, Java, C#, C++, Dart, or UE5. This is the recommended path for app/device actions.

## Server-Local Registration

```python
from yumi.core.platform.tools.tool import register_tool


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
    default_require_confirmation=False,
    confirmation_template=None,
) -> None
```

Parameters:

- `func`: Python callable to expose as a tool. It may be sync or async.
- `description`: Human-readable description shown to the model. This is one of the most important fields.
- `name`: Optional tool name override. Defaults to `func.__name__`.
- `params`: Optional mapping of argument name to description, for example `{"city": "City name"}`.
- `returns`: Optional return-value description appended to the tool description.
- `allow_proactive`: Allows proactive messaging to expose this read-only tool to the model. Default: `false`.
- `proactive_context`: Calls this tool before every normal chat reply and proactive message, then injects its result as read-only context for that turn only. Default: `false`. In edge SDKs, prefer `mode="autorun"`.
- `proactive_context_args`: Fixed arguments used for autorun context calls.
- `proactive_context_description`: Label shown when injecting autorun context, for example `Current weather`.
- `default_require_confirmation`: If `true`, the tool is added to the runtime confirmation set on startup (unless the user has opted into `local_tools_always_allow`). Use for high-blast-radius tools such as filesystem or network mutations. Default: `false`.

Type hints are converted into JSON schema. Supported common types include `str`, `int`, `float`, `bool`, `list`, `dict`, and simple optional types. Parameters without defaults are required.

## User-facing action descriptions

Supply optional `confirmation_template` on server-local/Python tools, or
`confirmationTemplate` / `ConfirmationTemplate` on other SDK options. It explains
the pending action without making users read function names and JSON:

```python
agent.register(
    get_weather,
    "Get weather for a city and day.",
    confirmation_template={
        "zh": "查询「{city}」「{day}」的天气",
        "en": "Check the weather in {city} for {day}",
    },
    require_confirmation=True,
)
```

The server substitutes **actual arguments and advertised schema defaults**.
Only top-level `{parameter}` placeholders are accepted; attribute access,
indexing, conversions and formatting expressions are rejected. Secret-named
fields are redacted. Invalid, missing or overly long substitutions fall back to
the normal function/parameter presentation. The app keeps the original parameters
in expandable details and saves `action_summary` with the invocation history.
This metadata is excluded from the model's function schema and never grants tool
permission. Old registrations remain valid without it.

Python and TypeScript accept a locale map or a string; the other native SDK
options accept a string. Use a plain string for a single-language tool.

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
    mode="autorun",
    context_args={"city": "Auckland"},
    context_label="Current weather",
)

agent.run_in_background()
```

Common Python Edge options:

- `func`, `description`, `name`, `params`, `returns`: Same meaning as server-local registration.
- `timeout`: Optional per-tool execution timeout in seconds.
- `require_confirmation`: If `true`, the user must approve before the server invokes this Edge tool.
- `reply_on_success`: Default `true`. Set `false` for a terminal action such as
  starting music; see the successful completion contract below. Available in the
  Python SDK, `yumi.register`, server-local `register_tool`, and the wire protocol.
- `mode`: `"dynamic"` (default), `"pinned"` (schema exposed every turn), or `"autorun"` (run before every reply and inject result as context).
- `context_args`: Fixed arguments for a `mode="autorun"` tool.
- `context_label`: Label shown when a `mode="autorun"` result is injected.
- `always_include`: Deprecated. Prefer `mode="pinned"`.
- `allow_proactive`: If `true`, proactive messaging may use this tool.
- `proactive_context`: Deprecated. Prefer `mode="autorun"`.
- `proactive_context_args`: Deprecated. Prefer `context_args`.
- `proactive_context_description`: Deprecated. Prefer `context_label`.

The shortcut API in `yumi/__init__.py` mirrors the Python Edge SDK:

```python
import yumi

yumi.register(get_weather, "Get weather", allow_proactive=True)
yumi.run(edge_name="Weather App")
```

## Successful completion without another reply

```python
async def play_track(song_id: str):
    await player.play(song_id)
    return {"ok": True}  # Set ok=false and include error on failure.

agent.register(play_track, "Play the selected track as the last requested action.",
               reply_on_success=False)
```

`reply_on_success` is registration metadata, not a model-controlled function
argument. The default `true` preserves existing behavior. With `false`, an
explicit JSON object with `ok: true` and no non-empty `error` ends the turn after
the tool results are saved, without calling the model again. Python handlers may
return a dictionary (the SDK serializes it as JSON) or a JSON string. Plain text,
missing/invalid `ok`, `ok: false`, exceptions, timeouts, denied calls, and partial
failures do not silently complete. Normal confirmation and access checks apply.

This is for a final action, not a data lookup: describe that clearly so the model
does other requested work first. All calls in the current batch must opt in and
succeed. A batch containing other tools still receives normal follow-up so their
results are not lost. Existing assistant text before the call remains in history.

On terminal success the server emits `turn_complete` with `reply: "none"` and
`voice_capture: "pause"`. `yumi --voice` stops requesting TTS and closes its audio
streams immediately, then drains the HTTP stream normally. The process remains
alive waiting for Enter or a supported player's verified completion; no microphone is held while waiting. Voice wake and
voice interruption are unavailable until capture resumes. This signal confirms
tool execution, not that a media player has already reached a particular state.

The Room Control `music_play` registration uses this policy. Search, status,
enqueue, and mixed control functions retain their normal reply behavior. The
wire field is optional, so old registrations keep working; explicit SDK keyword
support currently covers Python. Generated/vendor SDK copies need updating when
opting in, together with the server and voice client.

## Other Edge SDKs

All Edge SDKs use the same wire-level metadata even if naming follows each language's style.

Universal fields:

- `name`: Tool name shown to the model.
- `description`: What the tool does and when to use it.
- `parameters`: JSON-schema-style parameter descriptors.
- `handler`: Function/closure called when Yumi invokes the tool.
- `timeout`: Optional timeout in seconds, where supported.
- `requireConfirmation` / `require_confirmation` / `RequireConfirmation`: Require user approval.
- `mode`: `"dynamic"` (default), `"pinned"`, or `"autorun"` where the SDK supports exposure-mode sugar.
- `contextArgs` / `context_args` / `ContextArgs`: Fixed args for an autorun context tool.
- `contextLabel` / `context_label` / `ContextLabel`: Label for an autorun context result.
- `alwaysInclude` / `always_include` / `AlwaysInclude`: Deprecated. Prefer `mode="pinned"` where available.
- `allowProactive` / `allow_proactive` / `AllowProactive`: Allow proactive messaging to use this tool.
- `proactiveContext` / `proactive_context` / `ProactiveContext`: Deprecated. Prefer `mode="autorun"` where available.
- `proactiveContextArgs` / `proactive_context_args` / `ProactiveContextArgs`: Deprecated. Prefer `contextArgs`.
- `proactiveContextDescription` / `proactive_context_description` / `ProactiveContextDescription`: Deprecated. Prefer `contextLabel`.

Example TypeScript:

```typescript
agent.register({
  name: "get_weather",
  description: "Get current weather for a city.",
  parameters: [{ name: "city", type: "string", description: "City name" }],
  mode: "autorun",
  contextArgs: { city: "Auckland" },
  contextLabel: "Current weather",
  handler: async (args) => getWeather(String(args.city)),
});
```

Example Go:

```go
agent.Register(yumi.RegisterOptions{
    Name:        "get_weather",
    Description: "Get current weather for a city.",
    Mode:        "autorun",
    ContextArgs: map[string]interface{}{"city": "Auckland"},
    ContextLabel: "Current weather",
    Handler: func(args yumi.ToolArguments) string {
        return getWeather(args.String("city"))
    },
})
```

## Safety Rules

Use `require_confirmation=True` for irreversible or sensitive actions, such as deleting files, sending money, placing orders, unlocking doors, or changing device state in a risky way.

Do not mark side-effect tools as proactive or autorun. Proactive messaging is unattended, and autorun context runs before ordinary chat replies, so `allow_proactive` and `mode="autorun"` / `proactive_context` should be limited to safe read-only tools such as time, weather, calendar summaries, study progress, room status, or clock-in status checks.

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
