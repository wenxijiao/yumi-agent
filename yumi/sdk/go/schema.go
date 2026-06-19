package yumi_sdk

import "fmt"

// BuildToolSchema creates the JSON schema object for a registered tool,
// matching the wire format expected by the Yumi server.
//
// It panics if opts.Mode is set to anything other than "dynamic", "pinned",
// or "autorun" (an invalid mode is a programming error, surfaced at register time).
func BuildToolSchema(opts RegisterOptions) map[string]interface{} {
	// Map the Mode API onto the existing wire flags (one mode per tool).
	alwaysInclude := opts.AlwaysInclude
	proactiveContext := opts.ProactiveContext
	proactiveContextArgs := opts.ProactiveContextArgs
	proactiveContextDescription := opts.ProactiveContextDescription
	switch opts.Mode {
	case "", "dynamic":
		// no change
	case "pinned":
		alwaysInclude = true
	case "autorun":
		proactiveContext = true
		if opts.ContextArgs != nil {
			proactiveContextArgs = opts.ContextArgs
		}
		if opts.ContextLabel != "" {
			proactiveContextDescription = opts.ContextLabel
		}
	default:
		panic(fmt.Sprintf("mode must be 'dynamic', 'pinned', or 'autorun'; got %q", opts.Mode))
	}

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
	if alwaysInclude {
		schema["always_include"] = true
	}
	if opts.AllowProactive {
		schema["allow_proactive"] = true
	}
	if proactiveContext {
		schema["proactive_context"] = true
	}
	if proactiveContextArgs != nil {
		schema["proactive_context_args"] = proactiveContextArgs
	}
	if proactiveContextDescription != "" {
		schema["proactive_context_description"] = proactiveContextDescription
	}

	return schema
}
