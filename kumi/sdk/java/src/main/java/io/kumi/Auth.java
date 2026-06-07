package io.kumi;

import com.google.gson.Gson;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.Base64;

/**
 * Authentication helpers: base64url decode, LAN code / relay credential
 * parsing, and relay bootstrap.
 */
public final class Auth {
    private Auth() {}

    private static final String TOKEN_PREFIX = "kumi_";
    private static final String LAN_TOKEN_PREFIX = "kumi-lan_";
    private static final String[] LEGACY_LAN_PREFIXES = {"ml1_", "kumi_lan_"};

    static byte[] b64urlDecode(String data) {
        int padding = (4 - data.length() % 4) % 4;
        String padded = data + "=".repeat(padding);
        return Base64.getUrlDecoder().decode(padded);
    }

    /**
     * Decode a {@code kumi-lan_} token into host and port.
     */
    public static String[] decodeLanCode(String token) {
        String encoded;
        if (token.startsWith(LAN_TOKEN_PREFIX)) {
            encoded = token.substring(LAN_TOKEN_PREFIX.length());
        } else {
            encoded = null;
            for (String prefix : LEGACY_LAN_PREFIXES) {
                if (token.startsWith(prefix)) {
                    encoded = token.substring(prefix.length());
                    break;
                }
            }
            if (encoded == null) {
                throw new IllegalArgumentException("Invalid Kumi LAN code prefix.");
            }
        }

        String json = new String(b64urlDecode(encoded), StandardCharsets.UTF_8);
        JsonObject data = JsonParser.parseString(json).getAsJsonObject();

        String host;
        int port;
        if (data.has("h")) {
            host = data.get("h").getAsString();
            port = data.has("p") ? data.get("p").getAsInt() : 8000;
        } else if (data.has("base_url")) {
            URI uri = URI.create(data.get("base_url").getAsString());
            host = uri.getHost();
            if (host == null || host.isEmpty()) {
                throw new IllegalArgumentException("LAN code missing host.");
            }
            port = uri.getPort() > 0 ? uri.getPort() : 8000;
        } else {
            throw new IllegalArgumentException("LAN code missing host.");
        }

        if (data.has("x")) {
            long expiry = data.get("x").getAsLong();
            if (expiry > 0 && expiry < Instant.now().getEpochSecond()) {
                throw new IllegalArgumentException("LAN code has expired.");
            }
        }

        return new String[]{host, String.valueOf(port)};
    }

    /**
     * Decode a {@code kumi_} relay credential token.
     */
    public static JsonObject decodeCredential(String token) {
        if (!token.startsWith(TOKEN_PREFIX)) {
            throw new IllegalArgumentException("Invalid Kumi credential prefix.");
        }
        String json = new String(b64urlDecode(token.substring(TOKEN_PREFIX.length())), StandardCharsets.UTF_8);
        return JsonParser.parseString(json).getAsJsonObject();
    }

    /**
     * Contact the relay to obtain an access token.
     */
    public static BootstrapResult bootstrapProfile(String joinCode, String scope, String deviceName)
            throws IOException, InterruptedException {
        JsonObject cred = decodeCredential(joinCode);
        String relayUrl = cred.get("relay_url").getAsString().replaceAll("/+$", "");

        JsonObject payload = new JsonObject();
        payload.addProperty("join_code", joinCode);
        payload.addProperty("scope", scope);
        payload.addProperty("device_name", deviceName != null ? deviceName.trim() : "");

        HttpClient client = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(15))
                .build();

        HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create(relayUrl + "/v1/bootstrap"))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(new Gson().toJson(payload)))
                .timeout(Duration.ofSeconds(15))
                .build();

        HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() >= 400) {
            throw new IOException("Bootstrap failed: " + response.body());
        }

        JsonObject result = JsonParser.parseString(response.body()).getAsJsonObject();
        if (!result.has("access_token") || result.get("access_token").getAsString().isEmpty()) {
            throw new IOException("Bootstrap response missing access_token.");
        }

        return new BootstrapResult(relayUrl, result.get("access_token").getAsString());
    }

    static boolean isLanCode(String code) {
        if (code.startsWith(LAN_TOKEN_PREFIX)) return true;
        for (String prefix : LEGACY_LAN_PREFIXES) {
            if (code.startsWith(prefix)) return true;
        }
        return false;
    }

    static boolean isRelayToken(String code) {
        return code.startsWith(TOKEN_PREFIX) && !isLanCode(code);
    }

    static String parseLanCode(String code) {
        String[] hp = decodeLanCode(code);
        return "http://" + hp[0] + ":" + hp[1];
    }

    public static class BootstrapResult {
        public final String relayUrl;
        public final String accessToken;

        BootstrapResult(String relayUrl, String accessToken) {
            this.relayUrl = relayUrl;
            this.accessToken = accessToken;
        }
    }
}
