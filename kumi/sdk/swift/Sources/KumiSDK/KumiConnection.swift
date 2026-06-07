import Foundation

// MARK: - Connection config

struct ConnectionConfig {
    enum Mode { case direct, relay }

    let mode: Mode
    let baseURL: String
    let accessToken: String?

    var relayEdgeWSURL: String {
        httpToWS(baseURL.hasSuffix("/") ? String(baseURL.dropLast()) : baseURL) + "/ws/edge"
    }

    var wsURL: String {
        mode == .relay ? relayEdgeWSURL : baseURL
    }
}

// MARK: - URL helpers

func httpToWS(_ url: String) -> String {
    if url.hasPrefix("https://") {
        return "wss://" + url.dropFirst("https://".count)
    }
    if url.hasPrefix("http://") {
        return "ws://" + url.dropFirst("http://".count)
    }
    return url
}

// MARK: - Connection resolution

/// Resolve a connection code (or environment variables) into a concrete
/// ``ConnectionConfig`` ready for WebSocket connection.
///
/// Priority mirrors the Python SDK:
///  1. ``KUMI_RELAY_URL`` + ``KUMI_ACCESS_TOKEN`` env vars
///  2. connectionCode prefix detection
///  3. Fallback to ``ws://127.0.0.1:8000/ws/edge``
func resolveConnection(
    code: String?,
    edgeName: String,
    env: [String: String]
) async throws -> ConnectionConfig {
    // 1) Explicit relay env vars
    if let relayURL = env["KUMI_RELAY_URL"], !relayURL.isEmpty,
       let accessToken = env["KUMI_ACCESS_TOKEN"], !accessToken.isEmpty {
        return ConnectionConfig(
            mode: .relay,
            baseURL: relayURL.hasSuffix("/") ? String(relayURL.dropLast()) : relayURL,
            accessToken: accessToken
        )
    }

    let code = code ?? ""

    // 2a) Direct WebSocket URL
    if code.hasPrefix("ws://") || code.hasPrefix("wss://") {
        return ConnectionConfig(mode: .direct, baseURL: code, accessToken: nil)
    }

    // 2b) LAN code
    if code.hasPrefix(lanTokenPrefix) || legacyLanPrefixes.contains(where: { code.hasPrefix($0) }) {
        let lan = try decodeLanCode(code)
        let wsURL = "ws://\(lan.host):\(lan.port)/ws/edge"
        return ConnectionConfig(mode: .direct, baseURL: wsURL, accessToken: nil)
    }

    // 2c) Relay join token
    if code.hasPrefix(tokenPrefix) {
        let (relayURL, accessToken) = try await bootstrapProfile(
            joinCode: code,
            scope: "edge",
            deviceName: edgeName
        )
        return ConnectionConfig(
            mode: .relay,
            baseURL: relayURL,
            accessToken: accessToken
        )
    }

    // 2d) Plain HTTP URL → convert to WS
    if code.hasPrefix("http://") || code.hasPrefix("https://") {
        let base = code.hasSuffix("/") ? String(code.dropLast()) : code
        let wsURL = httpToWS(base) + "/ws/edge"
        return ConnectionConfig(mode: .direct, baseURL: wsURL, accessToken: nil)
    }

    // 3) Fallback
    return ConnectionConfig(
        mode: .direct,
        baseURL: "ws://127.0.0.1:8000/ws/edge",
        accessToken: nil
    )
}
