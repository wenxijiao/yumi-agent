package yumi_sdk

import (
	"encoding/json"
	"fmt"
	"log"
	"math/rand"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

const (
	logPrefix                  = "[Yumi]"
	toolConfirmationFilename   = ".yumi_tool_confirmation.json"
)

type registeredTool struct {
	schema              map[string]interface{}
	handler             ToolHandler
	requireConfirmation bool
}

// YumiAgent is the Go edge client for Yumi.
type YumiAgent struct {
	connectionCode string
	edgeName       string
	policyBaseDir  string

	mu    sync.Mutex
	tools map[string]*registeredTool

	done   chan struct{}
	wg     sync.WaitGroup
	closed bool
}

// NewAgent creates a new YumiAgent with the given options.
func NewAgent(opts AgentOptions) *YumiAgent {
	var envFile string
	if opts.EnvPath != "" {
		envFile = opts.EnvPath
	} else {
		cwd, _ := os.Getwd()
		yumiToolsEnv := filepath.Join(cwd, "yumi_tools", ".env")
		rootEnv := filepath.Join(cwd, ".env")
		if fileExists(yumiToolsEnv) {
			envFile = yumiToolsEnv
		} else {
			envFile = rootEnv
		}
	}

	LoadEnvFile(envFile)

	absEnv, _ := filepath.Abs(envFile)
	policyBaseDir := filepath.Dir(absEnv)

	connectionCode := opts.ConnectionCode
	if connectionCode == "" {
		connectionCode = os.Getenv("YUMI_CONNECTION_CODE")
	}
	if connectionCode == "" {
		connectionCode = os.Getenv("BRAIN_URL")
	}

	edgeName := opts.EdgeName
	if edgeName == "" {
		edgeName = os.Getenv("EDGE_NAME")
	}
	if edgeName == "" {
		hostname, _ := os.Hostname()
		edgeName = hostname
	}

	return &YumiAgent{
		connectionCode: connectionCode,
		edgeName:       edgeName,
		policyBaseDir:  policyBaseDir,
		tools:          make(map[string]*registeredTool),
		done:           make(chan struct{}),
	}
}

// Register adds a tool to the agent.
func (a *YumiAgent) Register(opts RegisterOptions) {
	schema := BuildToolSchema(opts)

	a.mu.Lock()
	defer a.mu.Unlock()
	a.tools[opts.Name] = &registeredTool{
		schema:              schema,
		handler:             opts.Handler,
		requireConfirmation: opts.RequireConfirmation,
	}
}

// RunInBackground starts the WebSocket connect loop in a goroutine.
func (a *YumiAgent) RunInBackground() {
	a.mu.Lock()
	if len(a.tools) == 0 {
		log.Printf("%s Warning: no tools registered.", logPrefix)
	}
	a.mu.Unlock()

	a.wg.Add(1)
	go func() {
		defer a.wg.Done()
		a.connectLoop()
	}()
}

// Stop gracefully shuts down the agent.
func (a *YumiAgent) Stop() {
	a.mu.Lock()
	if a.closed {
		a.mu.Unlock()
		return
	}
	a.closed = true
	a.mu.Unlock()

	close(a.done)
	a.wg.Wait()
}

// stopReconnect signals the reconnect loop to exit without waiting on the
// worker WaitGroup (safe to call from inside a session goroutine).
func (a *YumiAgent) stopReconnect() {
	a.mu.Lock()
	if a.closed {
		a.mu.Unlock()
		return
	}
	a.closed = true
	a.mu.Unlock()
	close(a.done)
}

func (a *YumiAgent) connectLoop() {
	conn, err := ResolveConnection(a.connectionCode, a.edgeName)
	if err != nil {
		log.Printf("%s Failed to resolve connection: %v", logPrefix, err)
		return
	}

	var wsURL string
	if conn.Mode == "relay" {
		wsURL = conn.relayEdgeWsURL()
	} else {
		wsURL = conn.BaseURL
	}

	reconnectDelay := 3 * time.Second

	for {
		select {
		case <-a.done:
			return
		default:
		}

		err := a.runSession(wsURL, conn.AccessToken)
		select {
		case <-a.done:
			return
		default:
		}

		if err != nil {
			wait := reconnectDelayWithJitter(reconnectDelay)
			log.Printf("%s Connection lost: %v. Reconnecting in %v...", logPrefix, err, wait)
			select {
			case <-time.After(wait):
			case <-a.done:
				return
			}
			reconnectDelay *= 2
			if reconnectDelay > 30*time.Second {
				reconnectDelay = 30 * time.Second
			}
		} else {
			reconnectDelay = 3 * time.Second
		}
	}
}

// reconnectDelayWithJitter adds ±500ms uniform jitter to the base delay so many
// edge clients do not reconnect in the same instant after a relay restart (thundering herd).
func reconnectDelayWithJitter(base time.Duration) time.Duration {
	const jitterMax = 500 * time.Millisecond
	n := time.Duration(rand.Int63n(int64(2*jitterMax+1))) - jitterMax
	d := base + n
	if d < time.Second {
		return time.Second
	}
	return d
}

func (a *YumiAgent) runSession(wsURL, accessToken string) error {
	dialer := websocket.DefaultDialer
	ws, _, err := dialer.Dial(wsURL, nil)
	if err != nil {
		return fmt.Errorf("dial: %w", err)
	}
	defer ws.Close()

	a.mu.Lock()
	toolSchemas := make([]interface{}, 0, len(a.tools))
	for _, t := range a.tools {
		toolSchemas = append(toolSchemas, t.schema)
	}
	a.mu.Unlock()

	registerPayload := map[string]interface{}{
		"type":                      "register",
		"edge_name":                 a.edgeName,
		"tools":                     toolSchemas,
		"tool_confirmation_policy":  a.loadConfirmationPolicy(),
	}
	if accessToken != "" {
		registerPayload["access_token"] = accessToken
	}

	if err := ws.WriteJSON(registerPayload); err != nil {
		return fmt.Errorf("register: %w", err)
	}

	a.mu.Lock()
	toolCount := len(a.tools)
	a.mu.Unlock()
	log.Printf("%s Connected as [%s] with %d tool(s).", logPrefix, a.edgeName, toolCount)

	readErr := make(chan error, 1)
	msgCh := make(chan map[string]interface{}, 16)

	go func() {
		for {
			var msg map[string]interface{}
			if err := ws.ReadJSON(&msg); err != nil {
				readErr <- err
				return
			}
			msgCh <- msg
		}
	}()

	for {
		select {
		case <-a.done:
			ws.WriteMessage(websocket.CloseMessage,
				websocket.FormatCloseMessage(websocket.CloseNormalClosure, ""))
			return nil

		case err := <-readErr:
			return fmt.Errorf("read: %w", err)

		case msg := <-msgCh:
			msgType, _ := msg["type"].(string)
			switch msgType {
			case "persist_tool_confirmation_policy":
				a.handlePersistPolicy(msg)
			case "tool_call":
				go a.handleToolCall(ws, msg)
			case "cancel":
				// Go handlers run synchronously in their own goroutine;
				// there is no generic cancellation mechanism for goroutines.
			case "register_warning":
				dropped, _ := msg["skipped_tools"].([]interface{})
				log.Printf("%s Server did not mount %d tool(s): %v", logPrefix, len(dropped), dropped)
			case "register_rejected":
				reason, _ := msg["reason"].(string)
				if reason == "" {
					reason = "edge_name already in use"
				}
				log.Printf("%s Edge registration rejected by server: %s", logPrefix, reason)
				a.stopReconnect()
				return nil
			}
		}
	}
}

func (a *YumiAgent) handleToolCall(ws *websocket.Conn, msg map[string]interface{}) {
	toolName, _ := msg["name"].(string)
	callID, _ := msg["call_id"].(string)
	if callID == "" {
		callID = "unknown"
	}

	rawArgs, _ := msg["arguments"].(map[string]interface{})
	args := newToolArguments(rawArgs)

	cancelled := false
	var result string

	a.mu.Lock()
	tool, ok := a.tools[toolName]
	a.mu.Unlock()

	if !ok {
		result = fmt.Sprintf("Error: Tool '%s' is not registered on this edge.", toolName)
	} else {
		func() {
			defer func() {
				if r := recover(); r != nil {
					result = fmt.Sprintf("Error executing tool '%s': %v", toolName, r)
				}
			}()
			result = tool.handler(args)
		}()
	}

	reply := map[string]interface{}{
		"type":      "tool_result",
		"call_id":   callID,
		"result":    result,
		"cancelled": cancelled,
	}

	a.mu.Lock()
	defer a.mu.Unlock()
	_ = ws.WriteJSON(reply)
}

// ── confirmation policy ──

func (a *YumiAgent) confirmationPolicyPath() string {
	override := strings.TrimSpace(os.Getenv("YUMI_TOOL_CONFIRMATION_PATH"))
	if override != "" {
		return override
	}
	return filepath.Join(a.policyBaseDir, toolConfirmationFilename)
}

func (a *YumiAgent) loadConfirmationPolicy() map[string]interface{} {
	path := a.confirmationPolicyPath()
	data, err := os.ReadFile(path)
	if err != nil {
		return map[string]interface{}{
			"always_allow":  []string{},
			"force_confirm": []string{},
		}
	}

	var raw map[string]interface{}
	if err := json.Unmarshal(data, &raw); err != nil {
		return map[string]interface{}{
			"always_allow":  []string{},
			"force_confirm": []string{},
		}
	}

	aa := toStringSlice(raw["always_allow"])
	fc := toStringSlice(raw["force_confirm"])
	return map[string]interface{}{
		"always_allow":  aa,
		"force_confirm": fc,
	}
}

func (a *YumiAgent) saveConfirmationPolicy(data map[string]interface{}) {
	path := a.confirmationPolicyPath()
	dir := filepath.Dir(path)
	_ = os.MkdirAll(dir, 0o755)

	payload := map[string]interface{}{
		"always_allow":  toStringSlice(data["always_allow"]),
		"force_confirm": toStringSlice(data["force_confirm"]),
	}

	jsonData, err := json.MarshalIndent(payload, "", "  ")
	if err != nil {
		return
	}
	_ = os.WriteFile(path, jsonData, 0o644)
}

func (a *YumiAgent) handlePersistPolicy(msg map[string]interface{}) {
	aa := toStringSlice(msg["always_allow"])
	fc := toStringSlice(msg["force_confirm"])
	a.saveConfirmationPolicy(map[string]interface{}{
		"always_allow":  aa,
		"force_confirm": fc,
	})
}

// ── helpers ──

func toStringSlice(v interface{}) []string {
	if v == nil {
		return []string{}
	}
	arr, ok := v.([]interface{})
	if !ok {
		if s, ok := v.([]string); ok {
			return s
		}
		return []string{}
	}
	out := make([]string, 0, len(arr))
	for _, item := range arr {
		if s := fmt.Sprintf("%v", item); s != "" {
			out = append(out, s)
		}
	}
	return out
}

func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}
