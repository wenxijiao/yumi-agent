package io.kumi;

import java.io.IOException;

/**
 * Connection resolution: determines WebSocket URL and access token
 * from environment variables and connection code.
 */
public final class Connection {
    private Connection() {}

    public static class ConnectionConfig {
        public final String mode;    // "direct" or "relay"
        public final String baseUrl;
        public final String accessToken;

        ConnectionConfig(String mode, String baseUrl, String accessToken) {
            this.mode = mode;
            this.baseUrl = baseUrl;
            this.accessToken = accessToken;
        }

        public String relayEdgeWsUrl() {
            return httpToWs(baseUrl.replaceAll("/+$", "")) + "/ws/edge";
        }
    }

    public static String httpToWs(String url) {
        if (url.startsWith("https://")) return "wss://" + url.substring("https://".length());
        if (url.startsWith("http://")) return "ws://" + url.substring("http://".length());
        return url;
    }

    public static ConnectionConfig resolveConnection(String code, String edgeName)
            throws IOException, InterruptedException {
        String relayUrl = System.getenv("KUMI_RELAY_URL");
        String accessToken = System.getenv("KUMI_ACCESS_TOKEN");
        if (relayUrl != null && !relayUrl.isEmpty() && accessToken != null && !accessToken.isEmpty()) {
            return new ConnectionConfig("relay", relayUrl.replaceAll("/+$", ""), accessToken);
        }

        if (code == null) code = "";

        if (code.startsWith("ws://") || code.startsWith("wss://")) {
            return new ConnectionConfig("direct", code, null);
        }

        if (Auth.isLanCode(code)) {
            String serverUrl = Auth.parseLanCode(code);
            String wsUrl = httpToWs(serverUrl.replaceAll("/+$", "")) + "/ws/edge";
            return new ConnectionConfig("direct", wsUrl, null);
        }

        if (Auth.isRelayToken(code)) {
            Auth.BootstrapResult profile = Auth.bootstrapProfile(code, "edge", edgeName);
            return new ConnectionConfig("relay", profile.relayUrl, profile.accessToken);
        }

        if (code.startsWith("http://") || code.startsWith("https://")) {
            String wsUrl = httpToWs(code.replaceAll("/+$", "")) + "/ws/edge";
            return new ConnectionConfig("direct", wsUrl, null);
        }

        return new ConnectionConfig("direct", "ws://127.0.0.1:8000/ws/edge", null);
    }
}
