import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

private let logPrefix = "[Yumi]"
private let confirmationFilename = ".yumi_tool_confirmation.json"

// MARK: - Registered tool entry

private struct RegisteredTool {
    let schema: [String: Any]
    let handler: @Sendable (ToolArguments) async throws -> String
    let requireConfirmation: Bool
}

// MARK: - YumiAgent

/// Embeddable Yumi edge client for Swift.
///
/// The usual approach on iOS is to pass ``connectionCode`` and ``edgeName`` from your app code
/// (e.g. constants in ``YumiSetup.swift``). Bundle resources, scheme env vars, and ``.env``-style
/// files are optional; see the edge template README.
///
/// Usage:
/// ```swift
/// import YumiSDK
///
/// let agent = YumiAgent(connectionCode: "yumi-lan_...", edgeName: "My iPhone")
///
/// try agent.register(
///     name: "set_light",
///     description: "Control room lights",
///     parameters: [
///         .init("room", type: .string, description: "Room name"),
///         .init("on", type: .boolean, description: "Turn on/off"),
///     ]
/// ) { args in
///     let room = args.string("room") ?? "living_room"
///     let on = args.bool("on") ?? false
///     return setLight(room: room, on: on)
/// }
///
/// agent.runInBackground()
/// ```
public final class YumiAgent: @unchecked Sendable {

    // MARK: - Configuration

    private let connectionCode: String?
    private let edgeName: String
    private let envVars: [String: String]
    private let policyBaseDir: String

    // MARK: - State

    private var tools: [String: RegisteredTool] = [:]
    private var backgroundTask: Task<Void, Never>?
    private var inFlightTasks: [String: Task<Void, Never>] = [:]

    // MARK: - Init

    /// Create a new Yumi edge agent.
    ///
    /// - Parameters:
    ///   - connectionCode: Server connection code (LAN code, relay token,
    ///     or WebSocket URL).  Falls back to ``YUMI_CONNECTION_CODE``
    ///     / ``BRAIN_URL`` env vars, then ``.env`` files.
    ///   - edgeName: Human-readable name shown in the server UI.
    ///     Falls back to ``EDGE_NAME`` env var, then the hostname.
    ///   - envPath: Absolute path to a dotenv-style file (optional).
    public init(
        connectionCode: String? = nil,
        edgeName: String? = nil,
        envPath: String? = nil
    ) {
        let resolved = Self.resolveEnvConfiguration(explicitPath: envPath)
        let fileEnv = resolved.envFileURL.flatMap { Self.parseEnvFile(at: $0.path) } ?? [:]

        // Process environment overrides .env file (same as Python SDK)
        func env(_ key: String) -> String? {
            ProcessInfo.processInfo.environment[key] ?? fileEnv[key]
        }

        self.connectionCode = connectionCode ?? env("YUMI_CONNECTION_CODE") ?? env("BRAIN_URL")
        self.edgeName = edgeName ?? env("EDGE_NAME") ?? ProcessInfo.processInfo.hostName
        self.policyBaseDir = resolved.policyBaseDir

        var merged: [String: String] = [:]
        for key in ["YUMI_RELAY_URL", "YUMI_ACCESS_TOKEN", "YUMI_CONNECTION_CODE", "BRAIN_URL", "EDGE_NAME"] {
            if let v = env(key) { merged[key] = v }
        }
        self.envVars = merged
    }

    /// Where we found key=value config and where to persist ``.yumi_tool_confirmation.json``.
    /// On a physical iPhone, cwd is not your project tree; config must come from the **app bundle**
    /// (or Xcode scheme env vars). Bundle files are read-only, so confirmation policy uses
    /// Application Support instead.
    private struct ResolvedEnvConfiguration {
        let envFileURL: URL?
        let policyBaseDir: String
    }

    private static func resolveEnvConfiguration(explicitPath: String?) -> ResolvedEnvConfiguration {
        let fm = FileManager.default

        if let explicitPath, !explicitPath.isEmpty {
            let expanded = (explicitPath as NSString).expandingTildeInPath
            let url = URL(fileURLWithPath: expanded).standardizedFileURL
            if fm.fileExists(atPath: url.path) {
                let policy: String
                if isPathInsideMainBundle(url.path) {
                    policy = writableYumiDataDirectory()
                } else {
                    policy = url.deletingLastPathComponent().path
                }
                return ResolvedEnvConfiguration(envFileURL: url, policyBaseDir: policy)
            }
        }

        #if os(iOS) || os(tvOS) || os(watchOS)
        if let url = findEnvInMainBundle() {
            return ResolvedEnvConfiguration(
                envFileURL: url,
                policyBaseDir: writableYumiDataDirectory()
            )
        }
        if let url = findEnvByWalkingUp(from: fm.currentDirectoryPath) {
            return ResolvedEnvConfiguration(
                envFileURL: url,
                policyBaseDir: url.deletingLastPathComponent().path
            )
        }
        #else
        if let url = findEnvByWalkingUp(from: fm.currentDirectoryPath) {
            return ResolvedEnvConfiguration(
                envFileURL: url,
                policyBaseDir: url.deletingLastPathComponent().path
            )
        }
        if let url = findEnvInMainBundle() {
            return ResolvedEnvConfiguration(
                envFileURL: url,
                policyBaseDir: writableYumiDataDirectory()
            )
        }
        #endif

        return ResolvedEnvConfiguration(
            envFileURL: nil,
            policyBaseDir: writableYumiDataDirectory()
        )
    }

    private static func isPathInsideMainBundle(_ path: String) -> Bool {
        let bundlePath = URL(fileURLWithPath: Bundle.main.bundlePath).standardizedFileURL.path
        let p = URL(fileURLWithPath: path).standardizedFileURL.path
        return p.hasPrefix(bundlePath + "/") || p == bundlePath
    }

    /// Writable directory for tool-confirmation policy when config lives in the read-only bundle.
    private static func writableYumiDataDirectory() -> String {
        let fm = FileManager.default
        guard let base = fm.urls(for: .applicationSupportDirectory, in: .userDomainMask).first else {
            return NSTemporaryDirectory()
        }
        let dir = base.appendingPathComponent("Yumi", isDirectory: true)
        try? fm.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.path
    }

    private static func findEnvByWalkingUp(from start: String) -> URL? {
        let fm = FileManager.default
        func candidate(in dir: String) -> URL? {
            let mt = (dir as NSString).appendingPathComponent("yumi_tools/.env")
            if fm.fileExists(atPath: mt) { return URL(fileURLWithPath: mt) }
            let root = (dir as NSString).appendingPathComponent(".env")
            if fm.fileExists(atPath: root) { return URL(fileURLWithPath: root) }
            return nil
        }
        var url = URL(fileURLWithPath: start, isDirectory: true).standardizedFileURL
        for _ in 0..<24 {
            if let hit = candidate(in: url.path) { return hit }
            let parent = url.deletingLastPathComponent()
            if parent.path == url.path { break }
            url = parent
        }
        return nil
    }

    /// Bundle resource lookups suitable for **iOS** (avoid leading-dot names where Xcode drops them).
    private static func findEnvInMainBundle() -> URL? {
        let fm = FileManager.default
        let b = Bundle.main

        let triples: [(String?, String?, String?)] = [
            ("env", nil, "yumi_tools"),
            ("yumi", "env", "yumi_tools"),
            ("YumiEnv", "txt", nil),
            ("YumiEnv", nil, "yumi_tools"),
        ]
        for (name, ext, sub) in triples {
            if let u = b.url(forResource: name, withExtension: ext, subdirectory: sub),
               fm.fileExists(atPath: u.path) {
                return u
            }
        }

        guard let res = b.resourceURL else { return nil }
        let relativePaths = [
            "yumi_tools/env",
            "yumi_tools/.env",
            "yumi.env",
        ]
        for rel in relativePaths {
            let u = res.appendingPathComponent(rel)
            if fm.fileExists(atPath: u.path) { return u }
        }

        return findEnvByWalkingUp(from: res.path)
    }

    private static func parseEnvFile(at path: String) -> [String: String] {
        guard FileManager.default.fileExists(atPath: path),
              let contents = try? String(contentsOfFile: path, encoding: .utf8) else {
            return [:]
        }
        var out: [String: String] = [:]
        for line in contents.components(separatedBy: .newlines) {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            if trimmed.isEmpty || trimmed.hasPrefix("#") { continue }
            let parts = trimmed.split(separator: "=", maxSplits: 1)
            guard parts.count == 2 else { continue }
            let key = String(parts[0]).trimmingCharacters(in: .whitespaces)
            var value = String(parts[1]).trimmingCharacters(in: .whitespaces)
            if (value.hasPrefix("\"") && value.hasSuffix("\""))
                || (value.hasPrefix("'") && value.hasSuffix("'")) {
                value = String(value.dropFirst().dropLast())
            }
            out[key] = value
        }
        return out
    }

    // MARK: - Public API

    /// Register a tool function.
    ///
    /// - Parameters:
    ///   - name: The tool name (shown to the LLM).
    ///   - description: What this tool does.
    ///   - parameters: Parameter descriptors for the JSON schema.
    ///   - timeout: Per-tool execution timeout in seconds.
    ///   - requireConfirmation: If true, the user must approve before the
    ///     server invokes this tool.
    ///   - mode: Exposure mode — `"dynamic"` (default), `"pinned"`, or `"autorun"`.
    ///     This is input sugar mapped onto the wire flags below; pick one per tool.
    ///   - contextArgs: Fixed arguments for an `"autorun"` tool.
    ///   - contextLabel: Label shown when an `"autorun"` result is injected.
    ///   - alwaysInclude: If true, this edge tool is exposed to the model on every turn.
    ///   - allowProactive: If true, proactive messaging may use this read-only tool.
    ///   - proactiveContext: If true, proactive messaging calls this tool before generation.
    ///   - proactiveContextArgs: Fixed arguments for proactive context calls.
    ///   - proactiveContextDescription: Label used when injecting proactive context.
    ///   - handler: The closure to execute. Receives ``ToolArguments`` and
    ///     returns a string result. May be async and throw.
    /// - Throws: ``YumiError/invalidMode(_:)`` if `mode` is not one of
    ///   `"dynamic"`, `"pinned"`, or `"autorun"`.
    public func register(
        name: String,
        description: String,
        parameters: [ToolParameter] = [],
        timeout: Int? = nil,
        requireConfirmation: Bool = false,
        mode: String = "dynamic",
        contextArgs: [String: Any]? = nil,
        contextLabel: String? = nil,
        alwaysInclude: Bool = false,
        allowProactive: Bool = false,
        proactiveContext: Bool = false,
        proactiveContextArgs: [String: Any]? = nil,
        proactiveContextDescription: String? = nil,
        handler: @escaping @Sendable (ToolArguments) async throws -> String
    ) throws {
        // Map the `mode` API onto the existing wire flags (one mode per tool).
        var resolvedAlwaysInclude = alwaysInclude
        var resolvedProactiveContext = proactiveContext
        var resolvedProactiveContextArgs = proactiveContextArgs
        var resolvedProactiveContextDescription = proactiveContextDescription
        switch mode {
        case "dynamic":
            break
        case "pinned":
            resolvedAlwaysInclude = true
        case "autorun":
            resolvedProactiveContext = true
            if let contextArgs { resolvedProactiveContextArgs = contextArgs }
            if let contextLabel { resolvedProactiveContextDescription = contextLabel }
        default:
            throw YumiError.invalidMode(mode)
        }

        let schema = buildToolSchema(
            name: name,
            description: description,
            parameters: parameters,
            timeout: timeout,
            requireConfirmation: requireConfirmation,
            alwaysInclude: resolvedAlwaysInclude,
            allowProactive: allowProactive,
            proactiveContext: resolvedProactiveContext,
            proactiveContextArgs: resolvedProactiveContextArgs,
            proactiveContextDescription: resolvedProactiveContextDescription
        )
        tools[name] = RegisteredTool(
            schema: schema,
            handler: handler,
            requireConfirmation: requireConfirmation
        )
    }

    /// Start the edge client in a detached background task.
    public func runInBackground() {
        guard backgroundTask == nil else { return }

        if tools.isEmpty {
            print("\(logPrefix) Warning: no tools registered.")
        }

        backgroundTask = Task.detached { [weak self] in
            await self?.connectLoop()
        }
    }

    /// Gracefully shut down the background client.
    public func stop() {
        backgroundTask?.cancel()
        backgroundTask = nil
        for (_, task) in inFlightTasks {
            task.cancel()
        }
        inFlightTasks.removeAll()
    }

    // MARK: - Confirmation policy

    private var confirmationPolicyPath: String {
        if let override = ProcessInfo.processInfo.environment["YUMI_TOOL_CONFIRMATION_PATH"],
           !override.trimmingCharacters(in: .whitespaces).isEmpty {
            return (override as NSString).expandingTildeInPath
        }
        return (policyBaseDir as NSString).appendingPathComponent(confirmationFilename)
    }

    private func loadConfirmationPolicy() -> [String: Any] {
        let path = confirmationPolicyPath
        guard FileManager.default.fileExists(atPath: path),
              let data = try? Data(contentsOf: URL(fileURLWithPath: path)),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return ["always_allow": [String](), "force_confirm": [String]()]
        }
        let aa = (json["always_allow"] as? [String]) ?? []
        let fc = (json["force_confirm"] as? [String]) ?? []
        return ["always_allow": aa, "force_confirm": fc]
    }

    private func saveConfirmationPolicy(_ data: [String: Any]) {
        let path = confirmationPolicyPath
        let dir = (path as NSString).deletingLastPathComponent
        try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
        let payload: [String: Any] = [
            "always_allow": (data["always_allow"] as? [String]) ?? [],
            "force_confirm": (data["force_confirm"] as? [String]) ?? [],
        ]
        guard let jsonData = try? JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted]) else {
            return
        }
        try? jsonData.write(to: URL(fileURLWithPath: path))
    }

    // MARK: - WebSocket lifecycle

    private func connectLoop() async {
        let connection: ConnectionConfig
        do {
            connection = try await resolveConnection(
                code: connectionCode,
                edgeName: edgeName,
                env: envVars
            )
        } catch {
            print("\(logPrefix) Failed to resolve connection: \(error.localizedDescription)")
            return
        }

        let wsURLString = connection.wsURL
        guard let wsURL = URL(string: wsURLString) else {
            print("\(logPrefix) Invalid WebSocket URL: \(wsURLString)")
            return
        }

        var reconnectDelay: UInt64 = 3

        while !Task.isCancelled {
            do {
                try await runSession(url: wsURL, connection: connection)
            } catch is CancellationError {
                break
            } catch {
                if Task.isCancelled { break }
                let baseNs = Int64(reconnectDelay) * 1_000_000_000
                let jitterNs = Int64.random(in: -500_000_000...500_000_000)
                let totalNs = max(Int64(1_000_000_000), baseNs + jitterNs)
                print("\(logPrefix) Connection lost: \(error.localizedDescription). Reconnecting in \(Double(totalNs) / 1e9)s...")
                try? await Task.sleep(nanoseconds: UInt64(totalNs))
                reconnectDelay = min(reconnectDelay * 2, 30)
            }
        }
    }

    private func runSession(url: URL, connection: ConnectionConfig) async throws {
        let session = URLSession(configuration: .default)
        let wsTask = session.webSocketTask(with: url)
        wsTask.resume()

        defer {
            wsTask.cancel(with: .goingAway, reason: nil)
            session.invalidateAndCancel()
            inFlightTasks.removeAll()
        }

        // Build and send register payload
        var registerPayload: [String: Any] = [
            "type": "register",
            "edge_name": edgeName,
            "tools": tools.values.map { wireToolSchema($0) },
            "tool_confirmation_policy": loadConfirmationPolicy(),
        ]
        if let token = connection.accessToken {
            registerPayload["access_token"] = token
        }

        let registerData = try JSONSerialization.data(withJSONObject: registerPayload)
        let registerString = String(data: registerData, encoding: .utf8) ?? "{}"
        try await wsTask.send(.string(registerString))

        print("\(logPrefix) Connected as [\(edgeName)] with \(tools.count) tool(s).")

        // Message receive loop
        while !Task.isCancelled {
            let message: URLSessionWebSocketTask.Message
            do {
                message = try await wsTask.receive()
            } catch {
                throw error
            }

            guard case .string(let text) = message,
                  let data = text.data(using: .utf8),
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                continue
            }

            let msgType = json["type"] as? String ?? ""

            switch msgType {
            case "tool_call":
                let callID = json["call_id"] as? String ?? "unknown"
                let task = Task { [weak self] in
                    guard let self else { return }
                    await self.handleToolCall(wsTask: wsTask, msg: json)
                }
                inFlightTasks[callID] = task

            case "cancel":
                let callID = json["call_id"] as? String ?? ""
                inFlightTasks[callID]?.cancel()
                inFlightTasks.removeValue(forKey: callID)

            case "persist_tool_confirmation_policy":
                saveConfirmationPolicy(json)

            case "register_warning":
                let dropped = (json["skipped_tools"] as? [Any])?.count ?? 0
                print("\(logPrefix) Server did not mount \(dropped) tool(s).")

            case "register_rejected":
                // Refused (edge_name in use). Stop — don't reconnect to be rejected again.
                let reason = json["reason"] as? String ?? "edge_name already in use"
                print("\(logPrefix) Edge registration rejected by server: \(reason)")
                stop()

            default:
                break
            }
        }
    }

    // MARK: - Tool call handling

    private func handleToolCall(wsTask: URLSessionWebSocketTask, msg: [String: Any]) async {
        let toolName = msg["name"] as? String ?? ""
        let arguments = msg["arguments"] as? [String: Any] ?? [:]
        let callID = msg["call_id"] as? String ?? "unknown"
        var cancelled = false
        let result: String

        guard let tool = tools[toolName] else {
            result = "Error: Tool '\(toolName)' is not registered on this edge."
            await sendResult(wsTask: wsTask, callID: callID, result: result, cancelled: false)
            return
        }

        let args = ToolArguments(arguments)
        do {
            try Task.checkCancellation()
            result = try await tool.handler(args)
        } catch is CancellationError {
            cancelled = true
            result = "Cancelled: Tool '\(toolName)' execution was cancelled by server."
        } catch {
            result = "Error executing tool '\(toolName)': \(error.localizedDescription)"
        }

        inFlightTasks.removeValue(forKey: callID)
        await sendResult(wsTask: wsTask, callID: callID, result: result, cancelled: cancelled)
    }

    private func sendResult(
        wsTask: URLSessionWebSocketTask,
        callID: String,
        result: String,
        cancelled: Bool
    ) async {
        let payload: [String: Any] = [
            "type": "tool_result",
            "call_id": callID,
            "result": result,
            "cancelled": cancelled,
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: payload),
              let text = String(data: data, encoding: .utf8) else {
            return
        }
        try? await wsTask.send(.string(text))
    }

    // MARK: - Helpers

    private func wireToolSchema(_ tool: RegisteredTool) -> [String: Any] {
        var schema = tool.schema
        if tool.requireConfirmation {
            schema["require_confirmation"] = true
        }
        return schema
    }
}
