package kumi_sdk

// BuildToolSchema creates the JSON schema object for a registered tool,
// matching the wire format expected by the Kumi server.
func BuildToolSchema(opts RegisterOptions) map[string]interface{} {
	properties := make(map[string]interface{})
	required := make([]string, 0)

	for _, p := range opts.Parameters {
		prop := map[string]interface{}{
			"type":        p.Type,
			"description": p.Description,
		}
		properties[p.Name] = prop

		isRequired := true
		if p.Required != nil {
			isRequired = *p.Required
		}
		if isRequired {
			required = append(required, p.Name)
		}
	}

	schema := map[string]interface{}{
		"type": "function",
		"function": map[string]interface{}{
			"name":        opts.Name,
			"description": opts.Description,
			"parameters": map[string]interface{}{
				"type":       "object",
				"properties": properties,
				"required":   required,
			},
		},
	}

	if opts.Timeout != nil {
		schema["timeout"] = *opts.Timeout
	}
	if opts.RequireConfirmation {
		schema["require_confirmation"] = true
	}
	if opts.AlwaysInclude {
		schema["always_include"] = true
	}
	if opts.AllowProactive {
		schema["allow_proactive"] = true
	}
	if opts.ProactiveContext {
		schema["proactive_context"] = true
	}
	if opts.ProactiveContextArgs != nil {
		schema["proactive_context_args"] = opts.ProactiveContextArgs
	}
	if opts.ProactiveContextDescription != "" {
		schema["proactive_context_description"] = opts.ProactiveContextDescription
	}

	return schema
}
