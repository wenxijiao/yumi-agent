package yumi_sdk

import (
	"encoding/json"
	"fmt"
)

// ToolParameter describes a single parameter in a tool's schema.
type ToolParameter struct {
	Name        string // JSON parameter name
	Type        string // "string", "integer", "number", "boolean", "array", "object"
	Description string
	Required    *bool // nil → required (default true)
}

// ToolArguments provides type-safe access to the arguments map sent by the server.
type ToolArguments struct {
	raw map[string]interface{}
}

func newToolArguments(raw map[string]interface{}) ToolArguments {
	if raw == nil {
		raw = make(map[string]interface{})
	}
	return ToolArguments{raw: raw}
}

func (a ToolArguments) Raw() map[string]interface{} { return a.raw }

func (a ToolArguments) String(key string) string {
	v, ok := a.raw[key]
	if !ok {
		return ""
	}
	s, ok := v.(string)
	if ok {
		return s
	}
	return fmt.Sprintf("%v", v)
}

func (a ToolArguments) Int(key string, fallback int) int {
	v, ok := a.raw[key]
	if !ok {
		return fallback
	}
	switch n := v.(type) {
	case float64:
		return int(n)
	case json.Number:
		i, err := n.Int64()
		if err != nil {
			return fallback
		}
		return int(i)
	default:
		return fallback
	}
}

func (a ToolArguments) Float(key string, fallback float64) float64 {
	v, ok := a.raw[key]
	if !ok {
		return fallback
	}
	switch n := v.(type) {
	case float64:
		return n
	case json.Number:
		f, err := n.Float64()
		if err != nil {
			return fallback
		}
		return f
	default:
		return fallback
	}
}

func (a ToolArguments) Bool(key string, fallback bool) bool {
	v, ok := a.raw[key]
	if !ok {
		return fallback
	}
	b, ok := v.(bool)
	if ok {
		return b
	}
	return fallback
}

func (a ToolArguments) StringSlice(key string) []string {
	v, ok := a.raw[key]
	if !ok {
		return nil
	}
	arr, ok := v.([]interface{})
	if !ok {
		return nil
	}
	out := make([]string, 0, len(arr))
	for _, item := range arr {
		out = append(out, fmt.Sprintf("%v", item))
	}
	return out
}

// ToolHandler is the callback invoked when the server sends a tool_call.
type ToolHandler func(args ToolArguments) string

// RegisterOptions describes a tool to register with the agent.
type RegisterOptions struct {
	Name                string
	Description         string
	Parameters          []ToolParameter
	Timeout             *int // per-tool timeout override (seconds)
	RequireConfirmation bool
	AlwaysInclude       bool // include this edge tool in every model request
	AllowProactive      bool // allow this tool in proactive messaging
	ProactiveContext    bool // call before proactive generation and inject result
	ProactiveContextArgs map[string]interface{}
	ProactiveContextDescription string
	Handler             ToolHandler
}

// AgentOptions configures YumiAgent construction.
type AgentOptions struct {
	ConnectionCode string // LAN code, relay token, WS URL, or HTTP URL
	EdgeName       string // human-readable name shown in server UI
	EnvPath        string // explicit .env file path (optional)
}
