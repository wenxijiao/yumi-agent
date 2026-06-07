import type { ToolParameter, RegisterOptions } from "./types";

export function buildToolSchema(opts: RegisterOptions): Record<string, unknown> {
  const properties: Record<string, Record<string, unknown>> = {};
  const required: string[] = [];

  for (const param of opts.parameters ?? []) {
    properties[param.name] = {
      type: param.type,
      description: param.description,
    };
    if (param.required !== false) {
      required.push(param.name);
    }
  }

  const schema: Record<string, unknown> = {
    type: "function",
    function: {
      name: opts.name,
      description: opts.description,
      parameters: {
        type: "object",
        properties,
        required,
      },
    },
  };

  if (opts.timeout != null) {
    schema.timeout = opts.timeout;
  }
  if (opts.requireConfirmation) {
    schema.require_confirmation = true;
  }
  if (opts.alwaysInclude) {
    schema.always_include = true;
  }
  if (opts.allowProactive) {
    schema.allow_proactive = true;
  }
  if (opts.proactiveContext) {
    schema.proactive_context = true;
  }
  if (opts.proactiveContextArgs != null) {
    schema.proactive_context_args = opts.proactiveContextArgs;
  }
  if (opts.proactiveContextDescription) {
    schema.proactive_context_description = opts.proactiveContextDescription;
  }

  return schema;
}
