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

    agent.run_in_background();
}
