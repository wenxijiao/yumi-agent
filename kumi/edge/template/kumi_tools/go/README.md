# Kumi Edge — Go

Use this when your app is written in Go and you want the LLM to call functions inside the same process.

## Quick Start

1. Add the local SDK module to your app's `go.mod`
2. Edit `kumi_tools/go/kumi_setup.go`
3. **Quick test:** from `kumi_tools/go/`, run `go run .` — `main.go` calls `InitKumi()` and blocks until Ctrl+C. When you embed Kumi in a larger app, remove `main.go` and call `InitKumi()` from your own `main`.
4. Otherwise call `InitKumi()` from your `main` and keep the process alive as usual

## Files In This Folder

```text
kumi_tools/go/
├── README.md
├── main.go                 # standalone entry (`go run .`); delete when embedding
├── kumi_setup.go          # edit this
└── kumi_sdk/              # bundled local Go module
    ├── go.mod
    ├── agent.go
    ├── auth.go
    ├── connection.go
    ├── schema.go
    ├── types.go
    └── env.go
```

## Add The SDK To Your Project

In your app's root `go.mod`:

```text
require kumi_sdk v0.0.0
replace kumi_sdk => ./kumi_tools/go/kumi_sdk
```

Then use it normally from your app source.

## Configure Connection

Edit the constants in `kumi_setup.go`, or use `kumi_tools/.env`:

```env
KUMI_CONNECTION_CODE=kumi-lan_...
EDGE_NAME=My Go App
```

## Register Tools

```go
agent.Register(kumi.RegisterOptions{
    Name:        "set_light",
    Description: "Control room lights",
    Parameters: []kumi.ToolParameter{
        {Name: "room", Type: "string", Description: "Room name"},
        {Name: "on", Type: "boolean", Description: "Turn on or off"},
    },
    Handler: func(args kumi.ToolArguments) string {
        room := args.String("room")
        on := args.Bool("on", false)
        return fmt.Sprintf("Light in %s: %v", room, on)
    },
})
```

Use `RequireConfirmation: true` for dangerous tools.

## Start It From Your App

```go
func main() {
    InitKumi()

    // your app continues to run
    select {}
}
```

## Notes

- Runtime dependency: `gorilla/websocket`
- Build with your normal Go workflow: `go run .` or `go build .`
