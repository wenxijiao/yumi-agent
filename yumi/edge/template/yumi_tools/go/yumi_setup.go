package main

import (
	"fmt"

	yumi "yumi_sdk"
)

// ── Configuration ──
// Set your connection code here (LAN: "yumi-lan_...", remote: "yumi_...").
// Leave empty to read from YUMI_CONNECTION_CODE env var or yumi_tools/.env.
const yumiConnectionCode = ""
const yumiEdgeName = "My Go App"

// InitYumi creates and starts the Yumi edge agent.
// Call from main.go (see yumi_tools/go/main.go) or from your own main.
func InitYumi() {
	agent := yumi.NewAgent(yumi.AgentOptions{
		ConnectionCode: yumiConnectionCode,
		EdgeName:       yumiEdgeName,
	})

	// Register your tools below.
	// Each tool needs a name, description, parameters, and a handler function.

	agent.Register(yumi.RegisterOptions{
		Name:        "hello",
		Description: "Say hello to someone",
		Parameters: []yumi.ToolParameter{
			{Name: "name", Type: "string", Description: "Person to greet"},
		},
		Handler: func(args yumi.ToolArguments) string {
			name := args.String("name")
			if name == "" {
				name = "World"
			}
			return fmt.Sprintf("Hello, %s!", name)
		},
	})

	// Example: tool with confirmation required
	// agent.Register(yumi.RegisterOptions{
	//     Name:                "dangerous_action",
	//     Description:         "Do something irreversible",
	//     RequireConfirmation: true,
	//     Handler: func(args yumi.ToolArguments) string {
	//         return "done"
	//     },
	// })
	//
	// Example: read-only tool allowed as proactive messaging context
	// agent.Register(yumi.RegisterOptions{
	//     Name:             "get_status",
	//     Description:      "Read current app status",
	//     AllowProactive:   true,
	//     ProactiveContext: true,
	//     Handler: func(args yumi.ToolArguments) string {
	//         return "ok"
	//     },
	// })

	agent.RunInBackground()
}
