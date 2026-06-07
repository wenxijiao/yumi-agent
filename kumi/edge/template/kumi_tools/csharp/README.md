# Kumi Edge — C#

Use this when your app is written in C# and you want to expose functions to Kumi through .NET 6+ native WebSocket.

## Quick Start

1. Add the bundled SDK to your project
2. Edit `kumi_tools/csharp/KumiSetup.cs`
3. **Quick test:** use `Program.cs` as the entry (add a `.csproj` that references `kumi_sdk`), then `dotnet run`. Remove `Program.cs` when you call `InitKumi()` from your own `Main`.
4. Otherwise call `KumiSetup.InitKumi()` from your app entry point and keep your process alive as usual

## Files In This Folder

```text
kumi_tools/csharp/
├── README.md
├── KumiSetup.cs          # edit this
├── Program.cs             # optional standalone entry; remove when embedding
└── kumi_sdk/             # bundled .NET project
    ├── KumiSDK.csproj
    └── *.cs
```

## Add The SDK To Your Project

Choose one of these approaches:

### Project reference

Add a project reference in your `.csproj`:

```xml
<ItemGroup>
    <ProjectReference Include="kumi_tools/csharp/kumi_sdk/KumiSDK.csproj" />
</ItemGroup>
```

### Copy sources

Copy the `.cs` files from `kumi_sdk/` into your project if that better fits your setup.

## Configure Connection

Edit the constants in `KumiSetup.cs`, or use `kumi_tools/.env`:

```env
KUMI_CONNECTION_CODE=kumi-lan_...
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
var agent = KumiSetup.InitKumi();
// ... your application logic ...
// Call agent.Stop() or agent.Dispose() on shutdown
Console.ReadLine(); // keep alive
```

## Notes

- Requires .NET 6+
- Uses native `System.Net.WebSockets.ClientWebSocket`
- Uses `System.Text.Json` — no external dependencies
