# Yumi Edge — C#

Use this when your app is written in C# and you want to expose functions to Yumi through .NET 6+ native WebSocket.

## Quick Start

1. Add the bundled SDK to your project
2. Edit `yumi_tools/csharp/YumiSetup.cs`
3. **Quick test:** use `Program.cs` as the entry (add a `.csproj` that references `yumi_sdk`), then `dotnet run`. Remove `Program.cs` when you call `InitYumi()` from your own `Main`.
4. Otherwise call `YumiSetup.InitYumi()` from your app entry point and keep your process alive as usual

## Files In This Folder

```text
yumi_tools/csharp/
├── README.md
├── YumiSetup.cs          # edit this
├── Program.cs             # optional standalone entry; remove when embedding
└── yumi_sdk/             # bundled .NET project
    ├── YumiSDK.csproj
    └── *.cs
```

## Add The SDK To Your Project

Choose one of these approaches:

### Project reference

Add a project reference in your `.csproj`:

```xml
<ItemGroup>
    <ProjectReference Include="yumi_tools/csharp/yumi_sdk/YumiSDK.csproj" />
</ItemGroup>
```

### Copy sources

Copy the `.cs` files from `yumi_sdk/` into your project if that better fits your setup.

## Configure Connection

Edit the constants in `YumiSetup.cs`, or use `yumi_tools/.env`:

```env
YUMI_CONNECTION_CODE=yumi-lan_...
EDGE_NAME=My C# App
```

## Register Tools

```csharp
agent.Register(new RegisterOptions()
    .SetName("set_light")
    .SetDescription("Control room lights")
    .SetParameters(
        new ToolParameter("room", "string", "Room name"),
        new ToolParameter("on", "boolean", "Turn on or off")
    )
    .SetHandler(args =>
    {
        var room = args.GetString("room", "living_room");
        var on = args.GetBool("on", false);
        return $"Light in {room}: {on}";
    })
);
```

Use `.SetRequireConfirmation(true)` for dangerous tools.

## Start It From Your App

```csharp
var agent = YumiSetup.InitYumi();
// ... your application logic ...
// Call agent.Stop() or agent.Dispose() on shutdown
Console.ReadLine(); // keep alive
```

## Notes

- Requires .NET 6+
- Uses native `System.Net.WebSockets.ClientWebSocket`
- Uses `System.Text.Json` — no external dependencies
