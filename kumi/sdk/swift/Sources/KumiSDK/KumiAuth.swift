import Foundation

// MARK: - Constants

let tokenPrefix = "kumi_"
let lanTokenPrefix = "kumi-lan_"
let legacyLanPrefixes = ["ml1_", "kumi_lan_"]

// MARK: - Decoded types

struct KumiCredential {
    let relayURL: String
    let tunnelID: String
    let scopes: [String]
    let expiresAt: Int
    let tokenID: String
    let label: String
    let deviceID: String?
}

struct KumiLanCode {
    let host: String
    let port: Int
}

// MARK: - Base64URL helpers

private func base64URLDecode(_ input: String) -> Data? {
    var base64 = input
        .replacingOccurrences(of: "-", with: "+")
        .replacingOccurrences(of: "_", with: "/")
    let remainder = base64.count % 4
    if remainder != 0 {
        base64.append(String(repeating: "=", count: 4 - remainder))
    }
    return Data(base64Encoded: base64)
}

// MARK: - Decode functions

enum AuthError: Error, LocalizedError {
    case invalidPrefix
    case decodeFailed
    case missingField(String)
    case expired
    case bootstrapFailed(String)

    var errorDescription: String? {
        switch self {
        case .invalidPrefix:       return "Invalid Kumi token prefix."
        case .decodeFailed:        return "Failed to decode Kumi token payload."
        case .missingField(let f): return "Token missing required field: \(f)"
        case .expired:             return "Token has expired."
        case .bootstrapFailed(let reason): return "Bootstrap failed: \(reason)"
        }
    }
}

/// Decode a ``kumi-lan_`` (or legacy prefix) LAN connection code into host + port.
func decodeLanCode(_ token: String) throws -> KumiLanCode {
    let encoded: String
    if token.hasPrefix(lanTokenPrefix) {
        encoded = String(token.dropFirst(lanTokenPrefix.count))
    } else if let prefix = legacyLanPrefixes.first(where: { token.hasPrefix($0) }) {
        encoded = String(token.dropFirst(prefix.count))
    } else {
        throw AuthError.invalidPrefix
    }

    guard let data = base64URLDecode(encoded),
          let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
        throw AuthError.decodeFailed
    }

    let host: String
    let port: Int

    if let h = json["h"] as? String {
        host = h
        port = (json["p"] as? Int) ?? 8000
    } else if let baseURL = json["base_url"] as? String,
              let comps = URLComponents(string: baseURL),
              let hostname = comps.host {
        host = hostname
        port = comps.port ?? 8000
    } else {
        throw AuthError.missingField("host")
    }

    if let expiresAt = json["x"] as? Int, expiresAt > 0,
       expiresAt < Int(Date().timeIntervalSince1970) {
        throw AuthError.expired
    }

    return KumiLanCode(host: host, port: port)
}

/// Decode a ``kumi_`` credential token into its fields.
func decodeCredential(_ token: String) throws -> KumiCredential {
    guard token.hasPrefix(tokenPrefix) else {
        throw AuthError.invalidPrefix
    }
    let encoded = String(token.dropFirst(tokenPrefix.count))

    guard let data = base64URLDecode(encoded),
          let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
        throw AuthError.decodeFailed
    }

    guard let relayURL = json["relay_url"] as? String else {
        throw AuthError.missingField("relay_url")
    }

    return KumiCredential(
        relayURL: relayURL,
        tunnelID: json["tunnel_id"] as? String ?? "",
        scopes: json["scopes"] as? [String] ?? [],
        expiresAt: json["expires_at"] as? Int ?? 0,
        tokenID: json["token_id"] as? String ?? "",
        label: json["label"] as? String ?? "",
        deviceID: json["device_id"] as? String
    )
}

/// POST to the relay's ``/v1/bootstrap`` endpoint with a join code,
/// returning the raw ``access_token`` string.
func bootstrapProfile(
    joinCode: String,
    scope: String,
    deviceName: String
) async throws -> (relayURL: String, accessToken: String) {
    let credential = try decodeCredential(joinCode)
    let relayURL = credential.relayURL.hasSuffix("/")
        ? String(credential.relayURL.dropLast())
        : credential.relayURL

    guard let url = URL(string: "\(relayURL)/v1/bootstrap") else {
        throw AuthError.bootstrapFailed("Invalid relay URL")
    }

    var request = URLRequest(url: url, timeoutInterval: 15)
    request.httpMethod = "POST"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")

    let body: [String: Any] = [
        "join_code": joinCode,
        "scope": scope,
        "device_name": deviceName,
    ]
    request.httpBody = try JSONSerialization.data(withJSONObject: body)

    let (data, response) = try await URLSession.shared.data(for: request)

    if let httpResp = response as? HTTPURLResponse, httpResp.statusCode != 200 {
        let detail = String(data: data, encoding: .utf8) ?? "HTTP \(httpResp.statusCode)"
        throw AuthError.bootstrapFailed(detail)
    }

    guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
          let accessToken = json["access_token"] as? String, !accessToken.isEmpty else {
        throw AuthError.bootstrapFailed("Response missing access_token")
    }

    return (relayURL, accessToken)
}
