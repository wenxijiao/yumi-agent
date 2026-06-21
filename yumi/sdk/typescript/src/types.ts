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
  args: ToolArguments,
  /** Aborted when the server cancels the call (e.g. on timeout). Optional —
   * long-running handlers can observe it; existing handlers can ignore it. */
  signal?: AbortSignal
) => Promise<string> | string;

/** Tool exposure mode (input sugar mapped onto the low-level wire flags). */
export type ToolMode = "dynamic" | "pinned" | "autorun";

export interface RegisterOptions {
  name: string;
  description: string;
  parameters?: ToolParameter[];
  timeout?: number;
  requireConfirmation?: boolean;
  /**
   * Exposure mode (pick one per tool):
   * - "dynamic" (default): joins dynamic top-K retrieval.
   * - "pinned": schema exposed to the model every turn (→ alwaysInclude).
   * - "autorun": run automatically before every reply, result injected as
   *   context (→ proactiveContext); use contextArgs / contextLabel.
   */
  mode?: ToolMode;
  /** Fixed arguments for an "autorun" tool (→ proactiveContextArgs). */
  contextArgs?: Record<string, unknown>;
  /** Label shown when an "autorun" result is injected (→ proactiveContextDescription). */
  contextLabel?: string;
  allowProactive?: boolean;
  // Deprecated low-level flags (prefer `mode`); still honored for back-compat.
  alwaysInclude?: boolean;
  proactiveContext?: boolean;
  proactiveContextArgs?: Record<string, unknown>;
  proactiveContextDescription?: string;
  handler: ToolHandler;
}
