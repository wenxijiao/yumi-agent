export interface ToolParameter {
  name: string;
  type: "string" | "integer" | "number" | "boolean" | "array" | "object";
  description: string;
  required?: boolean;
}

export class ToolArguments {
  constructor(private readonly raw: Record<string, unknown>) {}

  get rawData(): Record<string, unknown> {
    return this.raw;
  }

  string(key: string): string | undefined {
    const v = this.raw[key];
    return typeof v === "string" ? v : undefined;
  }

  int(key: string): number | undefined {
    const v = this.raw[key];
    if (typeof v === "number") return Math.round(v);
    return undefined;
  }

  number(key: string): number | undefined {
    const v = this.raw[key];
    return typeof v === "number" ? v : undefined;
  }

  bool(key: string): boolean | undefined {
    const v = this.raw[key];
    return typeof v === "boolean" ? v : undefined;
  }

  array(key: string): unknown[] | undefined {
    const v = this.raw[key];
    return Array.isArray(v) ? v : undefined;
  }

  stringArray(key: string): string[] | undefined {
    const v = this.raw[key];
    if (Array.isArray(v) && v.every((x) => typeof x === "string"))
      return v as string[];
    return undefined;
  }

  dict(key: string): Record<string, unknown> | undefined {
    const v = this.raw[key];
    if (v && typeof v === "object" && !Array.isArray(v))
      return v as Record<string, unknown>;
    return undefined;
  }
}

export type ToolHandler = (
  args: ToolArguments
) => Promise<string> | string;

export interface RegisterOptions {
  name: string;
  description: string;
  parameters?: ToolParameter[];
  timeout?: number;
  requireConfirmation?: boolean;
  alwaysInclude?: boolean;
  allowProactive?: boolean;
  proactiveContext?: boolean;
  proactiveContextArgs?: Record<string, unknown>;
  proactiveContextDescription?: string;
  handler: ToolHandler;
}
