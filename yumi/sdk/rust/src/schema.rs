use crate::types::RegisterOptions;
use serde_json::{json, Value};

pub fn build_tool_schema(opts: &RegisterOptions) -> Value {
    let mut properties = serde_json::Map::new();
    let mut required = Vec::new();

    for p in &opts.parameters {
        properties.insert(
            p.name.clone(),
            json!({
                "type": p.type_name,
                "description": p.description,
            }),
        );
        let is_required = p.required.unwrap_or(true);
        if is_required {
            required.push(p.name.clone());
        }
    }

    let mut schema = json!({
        "type": "function",
        "function": {
            "name": opts.name,
            "description": opts.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            }
        }
    });

    if let Some(t) = opts.timeout {
        schema
            .as_object_mut()
            .unwrap()
            .insert("timeout".to_string(), json!(t));
    }
    if opts.require_confirmation {
        schema
            .as_object_mut()
            .unwrap()
            .insert("require_confirmation".to_string(), json!(true));
    }
    if opts.always_include {
        schema
            .as_object_mut()
            .unwrap()
            .insert("always_include".to_string(), json!(true));
    }
    if opts.allow_proactive {
        schema
            .as_object_mut()
            .unwrap()
            .insert("allow_proactive".to_string(), json!(true));
    }
    if opts.proactive_context {
        schema
            .as_object_mut()
            .unwrap()
            .insert("proactive_context".to_string(), json!(true));
    }
    if let Some(args) = &opts.proactive_context_args {
        schema
            .as_object_mut()
            .unwrap()
            .insert("proactive_context_args".to_string(), args.clone());
    }
    if let Some(description) = &opts.proactive_context_description {
        schema
            .as_object_mut()
            .unwrap()
            .insert("proactive_context_description".to_string(), json!(description));
    }

    schema
}
