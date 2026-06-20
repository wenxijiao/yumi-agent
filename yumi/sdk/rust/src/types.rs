use std::sync::Arc;
use serde_json::Value;

/// Arguments for a tool invocation (`tool_call` from the server).
#[derive(Clone)]
pub struct ToolArguments {
    raw: serde_json::Map<String, serde_json::Value>,
}

impl ToolArguments {
    pub fn from_json(raw: serde_json::Map<String, serde_json::Value>) -> Self {
        Self { raw }
    }

    pub fn raw(&self) -> &serde_json::Map<String, serde_json::Value> {
        &self.raw
    }

    pub fn string(&self, key: &str) -> String {
        self.raw
            .get(key)
            .map(|v| match v {
                serde_json::Value::String(s) => s.clone(),
                _ => v.to_string().trim_matches('"').to_string(),
            })
            .unwrap_or_default()
    }

    pub fn int(&self, key: &str, fallback: i64) -> i64 {
        self.raw.get(key).map(json_as_i64).unwrap_or(fallback)
    }

    pub fn float(&self, key: &str, fallback: f64) -> f64 {
        self.raw.get(key).map(json_as_f64).unwrap_or(fallback)
    }

    pub fn bool_val(&self, key: &str, fallback: bool) -> bool {
        self.raw
            .get(key)
            .and_then(|v| v.as_bool())
            .unwrap_or(fallback)
    }
}

fn json_as_i64(v: &serde_json::Value) -> i64 {
    match v {
        serde_json::Value::Number(n) => n.as_i64().unwrap_or_else(|| n.as_f64().unwrap_or(0.0) as i64),
        _ => 0,
    }
}

fn json_as_f64(v: &serde_json::Value) -> f64 {
    match v {
        serde_json::Value::Number(n) => n.as_f64().unwrap_or(0.0),
        _ => 0.0,
    }
}

/// One parameter in a tool schema.
pub struct ToolParameter {
    pub name: String,
    pub type_name: String,
    pub description: String,
    /// `None` means required (default true), matching Go SDK.
    pub required: Option<bool>,
}

pub type ToolHandler = Arc<dyn Fn(ToolArguments) -> String + Send + Sync>;

/// Options for [`crate::YumiAgent::register`].
pub struct RegisterOptions {
    pub name: String,
    pub description: String,
    pub parameters: Vec<ToolParameter>,
    pub timeout: Option<u32>,
    pub require_confirmation: bool,
    /// Exposure mode — `"dynamic"` (default), `"pinned"`, or `"autorun"`.
    /// Mapped onto the low-level flags below before the wire schema is built:
    /// `"pinned"` -> `always_include`; `"autorun"` -> `proactive_context`
    /// (+ `context_args` / `context_label`).
    pub mode: String,
    /// Fixed arguments for an `"autorun"` tool. Maps to `proactive_context_args`.
    pub context_args: Option<Value>,
    /// Label shown when an `"autorun"` result is injected. Maps to
    /// `proactive_context_description`.
    pub context_label: Option<String>,
    pub allow_proactive: bool,
    // Low-level wire flags (prefer `mode`); still honored for back-compat.
    pub always_include: bool,
    pub proactive_context: bool,
    pub proactive_context_args: Option<Value>,
    pub proactive_context_description: Option<String>,
    pub handler: ToolHandler,
}

impl Default for RegisterOptions {
    fn default() -> Self {
        Self {
            name: String::new(),
            description: String::new(),
            parameters: Vec::new(),
            timeout: None,
            require_confirmation: false,
            mode: "dynamic".to_string(),
            context_args: None,
            context_label: None,
            allow_proactive: false,
            always_include: false,
            proactive_context: false,
            proactive_context_args: None,
            proactive_context_description: None,
            handler: Arc::new(|_| String::new()),
        }
    }
}

/// Options for [`crate::YumiAgent::new`].
pub struct AgentOptions {
    /// LAN code, relay token, `ws://` URL, or `http://` base URL.
    pub connection_code: Option<String>,
    pub edge_name: Option<String>,
    /// Path to `.env` (optional). Defaults to `yumi_tools/.env` or `./.env`.
    pub env_path: Option<String>,
}
