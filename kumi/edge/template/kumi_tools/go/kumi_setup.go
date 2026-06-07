package main

import (
	"fmt"

	kumi "kumi_sdk"
)

// ── Configuration ──
// Set your connection code here (LAN: "kumi-lan_...", remote: "kumi_...").
// Leave empty to read from KUMI_CONNECTION_CODE env var or kumi_tools/.env.
const kumiConnectionCode = ""
const kumiEdgeName = "My Go App"

// InitKumi creates and starts the Kumi edge agent.
// Call from main.go (see kumi_tools/go/main.go) or from your own main.
func InitKumi() {
	agent := kumi.NewAgent(kumi.AgentOptions{
		ConnectionCode: kumiConnectionCode,
		EdgeName:       kumiEdgeName,
	})

	// Register your tools below.
	// Each tool needs a name, description, parameters, and a handler function.

	agent.Register(kumi.RegisterOptions{
		Name:        "hello",
		Description: "Say hello to someone",
		Parameters: []kumi.ToolParameter{
			{Name: "name", Type: "string", Description: "Person to greet"},
		},
		Handler: func(args kumi.ToolArguments) string {
			name := args.String("name")
			if name == "" {
				name = "World"
			}
			return fmt.Sprintf("Hello, %s!", name)
		},
	})

	// Example: tool with confirmation required
	// agent.Register(kumi.RegisterOptions{
	//     Name:                "dangerous_action",
	//     Description:         "Do something irreversible",
	//     RequireConfirmation: true,
	//     Handler: func(args kumi.ToolArguments) string {
	//         return "done"
	//     },
	// })
	//
	// Example: read-only tool allowed as proactive messaging context
	// agent.Register(kumi.RegisterOptions{
	//     Name:             "get_status",
	//     Description:      "Read current app status",
	//     AllowProactive:   true,
	//     ProactiveContext: true,
	//     Handler: func(args kumi.ToolArguments) string {
	//         return "ok"
	//     },
	// })

	agent.RunInBackground()
}
