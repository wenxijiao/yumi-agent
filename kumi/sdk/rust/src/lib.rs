//! Kumi edge SDK for Rust — WebSocket client that registers tools with the Kumi server.
//!
//! ```no_run
//! use kumi_sdk::{AgentOptions, KumiAgent, RegisterOptions, ToolParameter};
//!
//! let agent = KumiAgent::new(AgentOptions {
//!     connection_code: None,
//!     edge_name: Some("My Rust App".into()),
//!     env_path: None,
//! });
//! agent.register(RegisterOptions {
//!     name: "hello".into(),
//!     description: "Say hello".into(),
//!     parameters: vec![ToolParameter {
//!         name: "name".into(),
//!         type_name: "string".into(),
//!         description: "Name".into(),
//!         required: None,
//!     }],
//!     require_confirmation: false,
//!     timeout: None,
//!     always_include: false,
//!     allow_proactive: false,
//!     proactive_context: false,
//!     proactive_context_args: None,
//!     proactive_context_description: None,
//!     handler: std::sync::Arc::new(|args| {
//!         format!("Hello, {}!", args.string("name"))
//!     }),
//! });
//! agent.run_in_background();
//! ```

mod agent;
mod auth;
mod connection;
mod env;
mod schema;
mod types;

pub use agent::KumiAgent;
pub use types::{AgentOptions, RegisterOptions, ToolArguments, ToolHandler, ToolParameter};
