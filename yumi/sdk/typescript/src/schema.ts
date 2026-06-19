import type { ToolParameter, RegisterOptions } from "./types";

export function buildToolSchema(opts: RegisterOptions): Record<string, unknown> {
  // Map the `mode` API onto the existing wire flags (one mode per tool).
  let alwaysInclude = opts.alwaysInclude ?? false;
  let proactiveContext = opts.proactiveContext ?? false;
  let proactiveContextArgs = opts.proactiveContextArgs;
  let proactiveContextDescription = opts.proactiveContextDescription;
  const mode = opts.mode ?? "dynamic";
  if (mode === "pinned") {
    alwaysInclude = true;
  } else if (mode === "autorun") {
    proactiveContext = true;
    if (opts.contextArgs != null) proactiveContextArgs = opts.contextArgs;
    if (opts.contextLabel != null) proactiveContextDescription = opts.contextLabel;
  } else if (mode !== "dynamic") {
    throw new Error(
      `mode must be 'dynamic', 'pinned', or 'autorun'; got ${JSON.stringify(mode)}`
    );
  }

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
  if (alwaysInclude) {
    schema.always_include = true;
  }
  if (opts.allowProactive) {
    schema.allow_proactive = true;
  }
  if (proactiveContext) {
    schema.proactive_context = true;
  }
  if (proactiveContextArgs != null) {
    schema.proactive_context_args = proactiveContextArgs;
  }
  if (proactiveContextDescription) {
    schema.proactive_context_description = proactiveContextDescription;
  }

  return schema;
}
