package yumi_sdk

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

const (
	tokenPrefix    = "yumi_"
	lanTokenPrefix = "yumi-lan_"
)

var legacyLanPrefixes = []string{"ml1_", "yumi_lan_"}

func b64urlDecode(data string) ([]byte, error) {
	padding := (4 - len(data)%4) % 4
	data += strings.Repeat("=", padding)
	return base64.URLEncoding.DecodeString(data)
}

// DecodeLanCode parses a yumi-lan_ token into host and port.
func DecodeLanCode(token string) (host string, port int, err error) {
	var encoded string

	if strings.HasPrefix(token, lanTokenPrefix) {
		encoded = token[len(lanTokenPrefix):]
	} else {
		found := false
		for _, p := range legacyLanPrefixes {
			if strings.HasPrefix(token, p) {
				encoded = token[len(p):]
				found = true
				break
			}
		}
		if !found {
			return "", 0, fmt.Errorf("invalid Yumi LAN code prefix")
		}
	}

	raw, err := b64urlDecode(encoded)
	if err != nil {
		return "", 0, fmt.Errorf("LAN code base64 decode error: %w", err)
	}

	var data map[string]interface{}
	if err := json.Unmarshal(raw, &data); err != nil {
		return "", 0, fmt.Errorf("LAN code JSON error: %w", err)
	}

	if h, ok := data["h"]; ok {
		host = fmt.Sprintf("%v", h)
		port = 8000
		if p, ok := data["p"]; ok {
			if pf, ok := p.(float64); ok {
				port = int(pf)
			}
		}
	} else if bu, ok := data["base_url"]; ok {
		u, err := url.Parse(fmt.Sprintf("%v", bu))
		if err != nil || u.Hostname() == "" {
			return "", 0, fmt.Errorf("LAN code missing host")
		}
		host = u.Hostname()
		port = 8000
		if u.Port() != "" {
			fmt.Sscanf(u.Port(), "%d", &port)
		}
	} else {
		return "", 0, fmt.Errorf("LAN code missing host")
	}

	if x, ok := data["x"]; ok {
		if xf, ok := x.(float64); ok && int64(xf) > 0 {
			if int64(xf) < time.Now().Unix() {
				return "", 0, fmt.Errorf("LAN code has expired")
			}
		}
	}

	return host, port, nil
}

// DecodeCredential parses a yumi_ relay token into its JSON payload.
func DecodeCredential(token string) (map[string]interface{}, error) {
	if !strings.HasPrefix(token, tokenPrefix) {
		return nil, fmt.Errorf("invalid Yumi credential prefix")
	}
	raw, err := b64urlDecode(token[len(tokenPrefix):])
	if err != nil {
		return nil, fmt.Errorf("credential base64 decode error: %w", err)
	}
	var data map[string]interface{}
	if err := json.Unmarshal(raw, &data); err != nil {
		return nil, fmt.Errorf("credential JSON error: %w", err)
	}
	return data, nil
}

// BootstrapResult holds the response from a relay bootstrap call.
type BootstrapResult struct {
	RelayURL    string
	AccessToken string
}

// BootstrapProfile contacts the relay server to obtain an access token.
func BootstrapProfile(joinCode, scope, deviceName string) (*BootstrapResult, error) {
	cred, err := DecodeCredential(joinCode)
	if err != nil {
		return nil, err
	}

	relayURL, ok := cred["relay_url"].(string)
	if !ok || relayURL == "" {
		return nil, fmt.Errorf("credential missing relay_url")
	}
	relayURL = strings.TrimRight(relayURL, "/")

	payload, _ := json.Marshal(map[string]string{
		"join_code":   joinCode,
		"scope":       scope,
		"device_name": strings.TrimSpace(deviceName),
	})

	client := &http.Client{Timeout: 15 * time.Second}
	resp, err := client.Post(relayURL+"/v1/bootstrap", "application/json", bytes.NewReader(payload))
	if err != nil {
		return nil, fmt.Errorf("bootstrap request failed: %w", err)
	}
	defer resp.Body.Close()

	body, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 400 {
		return nil, fmt.Errorf("bootstrap failed: %s", string(body))
	}

	var result map[string]interface{}
	if err := json.Unmarshal(body, &result); err != nil {
		return nil, fmt.Errorf("bootstrap response JSON error: %w", err)
	}

	at, ok := result["access_token"].(string)
	if !ok || at == "" {
		return nil, fmt.Errorf("bootstrap response missing access_token")
	}

	return &BootstrapResult{RelayURL: relayURL, AccessToken: at}, nil
}

func isLanCode(code string) bool {
	if strings.HasPrefix(code, lanTokenPrefix) {
		return true
	}
	for _, p := range legacyLanPrefixes {
		if strings.HasPrefix(code, p) {
			return true
		}
	}
	return false
}

func isRelayToken(code string) bool {
	return strings.HasPrefix(code, tokenPrefix) && !isLanCode(code)
}

func parseLanCode(code string) (string, error) {
	host, port, err := DecodeLanCode(code)
	if err != nil {
		return "", err
	}
	return fmt.Sprintf("http://%s:%d", host, port), nil
}
