# Kumi Edge — Unreal Engine 5

Use this when you want to expose UE5 gameplay or subsystem functions to Kumi.

## Quick Start

1. Copy the bundled `KumiSDK/` module into your project's `Source/` directory
2. Add `KumiSDK` to your game's `.Build.cs`
3. Edit `KumiSetup.h` / `KumiSetup.cpp`
4. Call `InitKumi()` early in your game lifecycle

## Add The Module

In your game's `.Build.cs`:

```csharp
PublicDependencyModuleNames.AddRange(new string[] { "KumiSDK" });
```

Then regenerate project files.

## Configure Connection

The simplest path is to edit `KumiConnectionCode` and `KumiEdgeName` directly in `KumiSetup.h`.

You can also place `kumi_tools/.env` in the project root:

```env
KUMI_CONNECTION_CODE=kumi-lan_...
EDGE_NAME=My UE5 Game
```

## Register Tools

```cpp
FKumiRegisterOptions Opts;
Opts.Name = TEXT("set_light");
Opts.Description = TEXT("Control room lights");
Opts.Parameters = {
    { TEXT("room"), TEXT("string"), TEXT("Room name"), true },
    { TEXT("on"), TEXT("boolean"), TEXT("Turn on or off"), true },
};
Opts.Handler.BindLambda([](const FKumiToolArguments& Args) -> FString {
    FString Room = Args.GetString(TEXT("room"), TEXT("living_room"));
    bool bOn = Args.GetBool(TEXT("on"), false);
    return SetLight(Room, bOn);
});
Agent->RegisterTool(MoveTemp(Opts));
```

Use `bRequireConfirmation = true` for dangerous tools.

## Start It From Your Game

Typical place:

```cpp
void UMyGameInstance::Init()
{
    Super::Init();
    InitKumi();
}
```

## Notes

- `FKumiAgent` is a plain C++ class, not a `UObject`
- Uses UE's own WebSocket, HTTP, and JSON modules
- Reconnects automatically with exponential backoff
