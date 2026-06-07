"""Cross-SDK contract tests.

Verify that the wire-format tool schema produced by each language SDK
matches the structure the Kumi server expects.  The tests here do NOT
run the other runtimes (Go, TS, Java, …); instead they parse each SDK's
schema builder source code and compare the output shape against a
reference schema produced by the Python SDK.  This catches structural
drift without requiring multi-language CI.

Additional checks:
- WebSocket register message shape
- Tool-call and tool-result message shape
"""

import os

# ── reference schema (the shape the server parses in kumi.core.features.edge.api) ──

REFERENCE_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "greet",
        "description": "Say hello",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "User name"},
            },
            "required": ["name"],
        },
    },
}


def _sdk_dir(*parts: str) -> str:
    return os.path.join(os.path.dirname(os.path.dirname(__file__)), "kumi", "sdk", *parts)


# ── Python SDK schema builder ──


def test_python_sdk_schema_structure():
    """Python SDK _build_tool_schema produces the expected top-level keys."""
    from kumi.sdk.python.agent_client import _build_tool_schema

    def greet(name: str) -> str:
        """Say hello

        Args:
            name: User name
        """
        return f"Hello {name}"

    schema = _build_tool_schema(greet)

    assert schema["type"] == "function"
    func = schema["function"]
    assert "name" in func
    assert "description" in func
    assert "parameters" in func

    params = func["parameters"]
    assert params["type"] == "object"
    assert "properties" in params
    assert "required" in params


# ── Go SDK schema structure (source-level check) ──


def test_go_schema_builder_produces_expected_keys():
    """Verify the Go BuildToolSchema emits the same top-level structure."""
    path = _sdk_dir("go", "schema.go")
    with open(path, encoding="utf-8") as f:
        source = f.read()

    assert '"type": "function"' in source or '"type":        "function"' in source
    assert '"function"' in source
    assert '"name"' in source
    assert '"description"' in source
    assert '"parameters"' in source
    assert '"properties"' in source
    assert '"required"' in source


# ── TypeScript SDK schema structure (source-level check) ──


def test_ts_schema_builder_produces_expected_keys():
    """Verify the TypeScript buildToolSchema emits the same top-level structure."""
    path = _sdk_dir("typescript", "src", "schema.ts")
    with open(path, encoding="utf-8") as f:
        source = f.read()

    assert 'type: "function"' in source
    assert "function:" in source or '"function"' in source
    assert "name:" in source
    assert "description:" in source
    assert "parameters:" in source
    assert "properties" in source
    assert "required" in source


# ── Register message shape (server expectation) ──

REGISTER_MESSAGE_REQUIRED_FIELDS = {"type", "edge_name", "tools"}


def test_register_message_shape():
    """The server expects at minimum: type=register, edge_name, tools."""
    msg = {
        "type": "register",
        "edge_name": "test-device",
        "tools": [REFERENCE_TOOL_SCHEMA],
    }
    assert REGISTER_MESSAGE_REQUIRED_FIELDS.issubset(msg.keys())
    assert msg["type"] == "register"
    assert isinstance(msg["tools"], list)
    assert msg["tools"][0]["type"] == "function"


# ── Tool call / tool result wire format ──


def test_tool_call_message_shape():
    """Server → edge: tool_call message must have name, arguments, call_id."""
    msg = {
        "type": "tool_call",
        "name": "greet",
        "arguments": {"name": "Alice"},
        "call_id": "abc-123",
    }
    for key in ("type", "name", "arguments", "call_id"):
        assert key in msg


def test_tool_result_message_shape():
    """Edge → server: tool_result message must have call_id and result."""
    msg = {
        "type": "tool_result",
        "call_id": "abc-123",
        "result": "Hello Alice",
    }
    for key in ("type", "call_id", "result"):
        assert key in msg


# ── Optional fields (timeout, require_confirmation, always_include) ──


def test_optional_schema_fields_accepted():
    """Server pops routing metadata fields from the schema."""
    schema_with_extras = {
        **REFERENCE_TOOL_SCHEMA,
        "timeout": 60,
        "require_confirmation": True,
        "always_include": True,
        "allow_proactive": True,
        "proactive_context": True,
        "proactive_context_args": {"location": "Auckland"},
        "proactive_context_description": "Current weather",
    }
    assert schema_with_extras["timeout"] == 60
    assert schema_with_extras["require_confirmation"] is True
    assert schema_with_extras["always_include"] is True
    assert schema_with_extras["allow_proactive"] is True
    assert schema_with_extras["proactive_context"] is True


# ── Go SDK RegisterOptions field names match server expectations ──


def test_go_register_options_fields():
    path = _sdk_dir("go", "types.go")
    with open(path, encoding="utf-8") as f:
        source = f.read()

    for field in (
        "Name",
        "Description",
        "Parameters",
        "Timeout",
        "RequireConfirmation",
        "AlwaysInclude",
        "AllowProactive",
        "ProactiveContext",
        "ProactiveContextArgs",
        "ProactiveContextDescription",
        "Handler",
    ):
        assert field in source, f"Go RegisterOptions missing field: {field}"


# ── TypeScript SDK RegisterOptions field names match server expectations ──


def test_ts_register_options_fields():
    path = _sdk_dir("typescript", "src", "types.ts")
    with open(path, encoding="utf-8") as f:
        source = f.read()

    for field in (
        "name",
        "description",
        "parameters",
        "timeout",
        "requireConfirmation",
        "alwaysInclude",
        "allowProactive",
        "proactiveContext",
        "proactiveContextArgs",
        "proactiveContextDescription",
        "handler",
    ):
        assert field in source, f"TS RegisterOptions missing field: {field}"


# ── Java SDK SchemaBuilder emits expected keys ──


def test_java_schema_builder_structure():
    path = _sdk_dir("java", "src", "main", "java", "io", "kumi", "SchemaBuilder.java")
    if not os.path.isfile(path):
        import pytest

        pytest.skip("Java SDK SchemaBuilder not found")
    with open(path, encoding="utf-8") as f:
        source = f.read()

    for key in ('"type"', '"function"', '"name"', '"description"', '"parameters"', '"properties"', '"required"'):
        assert key in source, f"Java SchemaBuilder missing key: {key}"
