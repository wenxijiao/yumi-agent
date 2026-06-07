import Foundation

// MARK: - Parameter type descriptor

/// Describes a single parameter that a tool accepts.
public struct ToolParameter: Sendable {
    public let name: String
    public let type: ParameterType
    public let description: String
    public let isRequired: Bool

    public enum ParameterType: String, Sendable {
        case string
        case integer
        case number
        case boolean
        case array
        case object
    }

    public init(
        _ name: String,
        type: ParameterType,
        description: String,
        required: Bool = true
    ) {
        self.name = name
        self.type = type
        self.description = description
        self.isRequired = required
    }
}

// MARK: - Schema builder

/// Builds the JSON tool-schema dict that the server expects on the
/// ``register`` WebSocket message.  Output matches the Python SDK's
/// ``_build_tool_schema`` structure.
func buildToolSchema(
    name: String,
    description: String,
    parameters: [ToolParameter],
    timeout: Int? = nil,
    requireConfirmation: Bool = false,
    alwaysInclude: Bool = false,
    allowProactive: Bool = false,
    proactiveContext: Bool = false,
    proactiveContextArgs: [String: Any]? = nil,
    proactiveContextDescription: String? = nil
) -> [String: Any] {
    var properties: [String: Any] = [:]
    var required: [String] = []

    for param in parameters {
        var prop: [String: Any] = [
            "type": param.type.rawValue,
            "description": param.description,
        ]
        if param.type == .integer {
            prop["type"] = "integer"
        }
        properties[param.name] = prop
        if param.isRequired {
            required.append(param.name)
        }
    }

    var schema: [String: Any] = [
        "type": "function",
        "function": [
            "name": name,
            "description": description,
            "parameters": [
                "type": "object",
                "properties": properties,
                "required": required,
            ] as [String: Any],
        ] as [String: Any],
    ]

    if let timeout {
        schema["timeout"] = timeout
    }
    if requireConfirmation {
        schema["require_confirmation"] = true
    }
    if alwaysInclude {
        schema["always_include"] = true
    }
    if allowProactive {
        schema["allow_proactive"] = true
    }
    if proactiveContext {
        schema["proactive_context"] = true
    }
    if let proactiveContextArgs {
        schema["proactive_context_args"] = proactiveContextArgs
    }
    if let proactiveContextDescription, !proactiveContextDescription.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
        schema["proactive_context_description"] = proactiveContextDescription
    }

    return schema
}
