package yumi_sdk

import (
	"os"
	"strings"
)

// ConnectionConfig holds resolved connection details.
type ConnectionConfig struct {
	Mode        string // "direct" or "relay"
	BaseURL     string
	AccessToken string
}

func (c *ConnectionConfig) relayEdgeWsURL() string {
	return httpToWs(strings.TrimRight(c.BaseURL, "/")) + "/ws/edge"
}

func httpToWs(u string) string {
	if strings.HasPrefix(u, "https://") {
		return "wss://" + u[len("https://"):]
	}
	if strings.HasPrefix(u, "http://") {
		return "ws://" + u[len("http://"):]
	}
	return u
}

// ResolveConnection determines the WebSocket connection target from
// environment variables and the user-provided connection code.
func ResolveConnection(code, edgeName string) (*ConnectionConfig, error) {
	relayURL := os.Getenv("YUMI_RELAY_URL")
	accessToken := os.Getenv("YUMI_ACCESS_TOKEN")
	if relayURL != "" && accessToken != "" {
		return &ConnectionConfig{
			Mode:        "relay",
			BaseURL:     strings.TrimRight(relayURL, "/"),
			AccessToken: accessToken,
		}, nil
	}

	if strings.HasPrefix(code, "ws://") || strings.HasPrefix(code, "wss://") {
		return &ConnectionConfig{Mode: "direct", BaseURL: code}, nil
	}

	if isLanCode(code) {
		serverURL, err := parseLanCode(code)
		if err != nil {
			return nil, err
		}
		wsURL := httpToWs(strings.TrimRight(serverURL, "/")) + "/ws/edge"
		return &ConnectionConfig{Mode: "direct", BaseURL: wsURL}, nil
	}

	if isRelayToken(code) {
		profile, err := BootstrapProfile(code, "edge", edgeName)
		if err != nil {
			return nil, err
		}
		os.Setenv("YUMI_RELAY_URL", profile.RelayURL)
		os.Setenv("YUMI_ACCESS_TOKEN", profile.AccessToken)
		return &ConnectionConfig{
			Mode:        "relay",
			BaseURL:     profile.RelayURL,
			AccessToken: profile.AccessToken,
		}, nil
	}

	if strings.HasPrefix(code, "http://") || strings.HasPrefix(code, "https://") {
		wsURL := httpToWs(strings.TrimRight(code, "/")) + "/ws/edge"
		return &ConnectionConfig{Mode: "direct", BaseURL: wsURL}, nil
	}

	return &ConnectionConfig{
		Mode:    "direct",
		BaseURL: "ws://127.0.0.1:8000/ws/edge",
	}, nil
}
