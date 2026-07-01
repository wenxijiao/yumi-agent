use yumi_sdk::{AgentOptions, YumiAgent, RegisterOptions, ToolParameter};
use std::sync::Arc;

/// Call this from `main` or embed in your own async runtime.
pub fn init_yumi() {
    let agent = YumiAgent::new(AgentOptions {
        connection_code: None,
        edge_name: Some("My Rust App".into()),
        env_path: None,
    });

    agent.register(RegisterOptions {
        name: "hello".into(),
        description: "Say hello to someone".into(),
        parameters: vec![ToolParameter {
            name: "name".into(),
            type_name: "string".into(),
            description: "Person to greet".into(),
            required: None,
        }],
        timeout: None,
        require_confirmation: false,
        // Exposure mode: "dynamic" (default), "pinned", or "autorun".
        mode: "dynamic".into(),
        context_args: None,
        context_label: None,
        always_include: false,
        allow_proactive: false,
        proactive_context: false,
        proactive_context_args: None,
        proactive_context_description: None,
        handler: Arc::new(|args| {
            let name = args.string("name");
            if name.is_empty() {
                "Hello, World!".into()
            } else {
                format!("Hello, {name}!")
            }
        }),
    });

    // Example tool — replace with your own. `mode: "pinned"` keeps it always
    // exposed to the agent. It echoes a message back so you can confirm the
    // edge is connected.
    agent.register(RegisterOptions {
        name: "ping".into(),
        description: "Ping the edge and echo a message back".into(),
        parameters: vec![ToolParameter {
            name: "message".into(),
            type_name: "string".into(),
            description: "Text to echo back.".into(),
            // Optional: defaults to "hello" in the handler when omitted.
            required: Some(false),
        }],
        timeout: None,
        require_confirmation: false,
        mode: "pinned".into(),
        context_args: None,
        context_label: None,
        always_include: false,
        allow_proactive: false,
        proactive_context: false,
        proactive_context_args: None,
        proactive_context_description: None,
        handler: Arc::new(|args| {
            let mut message = args.string("message");
            if message.is_empty() {
                message = "hello".into();
            }
            format!("pong: {message}")
        }),
    });

    agent.run_in_background();
}
