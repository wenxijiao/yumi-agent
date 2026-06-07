import Foundation

/// Type-safe wrapper around the raw JSON dictionary received in a tool call.
///
/// The struct holds decoded JSON primitives only, so the `@unchecked Sendable`
/// conformance at the bottom of this file is safe in practice.
public struct ToolArguments {
    private let raw: [String: Any]

    init(_ dictionary: [String: Any]) {
        self.raw = dictionary
    }

    /// Access the underlying dictionary directly.
    public var rawDictionary: [String: Any] { raw }

    public func string(_ key: String) -> String? {
        raw[key] as? String
    }

    public func int(_ key: String) -> Int? {
        if let v = raw[key] as? Int { return v }
        if let v = raw[key] as? Double { return Int(v) }
        if let v = raw[key] as? NSNumber { return v.intValue }
        return nil
    }

    public func double(_ key: String) -> Double? {
        if let v = raw[key] as? Double { return v }
        if let v = raw[key] as? Int { return Double(v) }
        if let v = raw[key] as? NSNumber { return v.doubleValue }
        return nil
    }

    public func bool(_ key: String) -> Bool? {
        if let v = raw[key] as? Bool { return v }
        if let v = raw[key] as? NSNumber { return v.boolValue }
        return nil
    }

    public func array(_ key: String) -> [Any]? {
        raw[key] as? [Any]
    }

    public func stringArray(_ key: String) -> [String]? {
        raw[key] as? [String]
    }

    public func dict(_ key: String) -> [String: Any]? {
        raw[key] as? [String: Any]
    }
}

// ToolArguments holds [String: Any] which isn't technically Sendable,
// but in practice it only contains JSON-primitive values from decoded
// server payloads.  The @unchecked annotation suppresses the warning.
extension ToolArguments: @unchecked Sendable {}
