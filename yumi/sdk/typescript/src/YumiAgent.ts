import type { RegisterOptions, ToolHandler } from "./types";
import { ToolArguments } from "./types";
import { buildToolSchema } from "./schema";
import { resolveConnection, relayEdgeWsUrl, type ConnectionConfig } from "./connection";
import { getEnv, getYumiEnv, isNode } from "./runtime";

const LOG_PREFIX = "[Yumi]";
const TOOL_CONFIRMATION_FILENAME = ".yumi_tool_confirmation.json";

interface RegisteredTool {
  schema: Record<string, unknown>;
  handler: ToolHandler;
}

interface ConfirmationPolicy {
  always_allow: string[];
  force_confirm: string[];
}

export interface YumiAgentOptions {
  connectionCode?: string;
  edgeName?: string;
  envPath?: string;
}

/** Active WebSocket session (browser native or `ws` on Node). */
interface YumiWsSession {
  send(data: string): void;
  close(): void;
}

function defaultEdgeName(opts: YumiAgentOptions): string {
  if (opts.edgeName) return opts.edgeName;
  const fromEnv = getEnv().EDGE_NAME;
  if (fromEnv) return fromEnv;
  if (isNode()) {
    try {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const os = require("os") as typeof import("os");
      return os.hostname();
    } catch {
      /* ignore */
    }
  }
  return "yumi-edge";
}

async function messageDataToString(data: unknown): Promise<string> {
  if (typeof data === "string") return data;
  if (data instanceof ArrayBuffer) return new TextDecoder("utf-8").decode(data);
  if (typeof Blob !== "undefined" && data instanceof Blob) return data.text();
  if (ArrayBuffer.isView(data)) {
    const view = data as ArrayBufferView;
    return new TextDecoder("utf-8").decode(
      new Uint8Array(view.buffer, view.byteOffset, view.byteLength)
    );
  }
  return String(data);
}

type WsHandlers = {
  /** Called with the active session so registration can send before `YumiAgent` field is set. */
  onOpen: (session: YumiWsSession) => void;
  onMessage: (text: string) => void;
  onClose: () => void;
  onError: (err: unknown) => void;
};

/**
 * Browser: `globalThis.WebSocket`. Node: dynamic `import("ws")` (not bundled for web).
 */
async function openIsomorphicWebSocket(
  url: string,
  handlers: WsHandlers
): Promise<YumiWsSession> {
  const NativeWS = globalThis.WebSocket;
  if (typeof NativeWS === "function") {
    const ws = new NativeWS(url);
    const session: YumiWsSession = {
      send: (d: string) => ws.send(d),
      close: () => {
        try {
          ws.close();
        } catch {
          /* ignore */
        }
      },
    };
    ws.addEventListener("open", () => handlers.onOpen(session));
    ws.addEventListener("message", (ev: MessageEvent) => {
      void messageDataToString(ev.data)
        .then(handlers.onMessage)
        .catch(() => {});
    });
    ws.addEventListener("close", () => handlers.onClose());
    ws.addEventListener("error", (ev: Event) => handlers.onError(ev));
    return session;
  }

  try {
    const wsMod = await import(
      /* webpackIgnore: true */
      /* @vite-ignore */
      "ws"
    );
    const WS = wsMod.default as typeof import("ws").WebSocket;
    const ws = new WS(url) as import("ws").WebSocket;
    const session: YumiWsSession = {
      send: (d: string) => ws.send(d),
      close: () => {
        try {
          ws.close();
        } catch {
          /* ignore */
        }
      },
    };
    ws.on("open", () => handlers.onOpen(session));
    ws.on("message", (data: import("ws").RawData) => {
      const text = Buffer.isBuffer(data)
        ? data.toString("utf-8")
        : typeof data === "string"
          ? data
          : String(data);
      handlers.onMessage(text);
    });
    ws.on("close", handlers.onClose);
    ws.on("error", handlers.onError);
    return session;
  } catch (e) {
    throw new Error(
      `Yumi SDK: no WebSocket implementation (browser WebSocket or Node package "ws"). ${String(e)}`
    );
  }
}

/** Load `.env` into `process.env` on Node only (dynamic `fs` — no top-level import). */
async function loadDotEnvFileIfNode(opts: YumiAgentOptions): Promise<{
  policyBaseDir: string;
}> {
  if (!isNode()) {
    return { policyBaseDir: "" };
  }
  try {
    const fs = await import(
      /* webpackIgnore: true */
      /* @vite-ignore */
      "fs"
    );
    const path = await import(
      /* webpackIgnore: true */
      /* @vite-ignore */
      "path"
    );

    let envFile: string;
    if (opts.envPath) {
      envFile = opts.envPath;
    } else {
      // Walk up from cwd so the edge finds yumi_tools/.env regardless of which
      // subdir it is launched from (e.g. cwd = <workspace>/yumi_tools/typescript,
      // with .env at <workspace>/yumi_tools/.env — the PARENT of the lang dir).
      const cwd = process.cwd();
      let dir = cwd;
      let found = "";
      for (;;) {
        const yumiToolsEnv = path.join(dir, "yumi_tools", ".env");
        if (fs.existsSync(yumiToolsEnv)) {
          found = yumiToolsEnv;
          break;
        }
        const rootEnv = path.join(dir, ".env");
        if (fs.existsSync(rootEnv)) {
          found = rootEnv;
          break;
        }
        const parent = path.dirname(dir);
        if (parent === dir) break; // reached filesystem root
        dir = parent;
      }
      envFile = found || path.join(cwd, ".env");
    }

    if (!fs.existsSync(envFile)) {
      return { policyBaseDir: path.dirname(path.resolve(envFile)) };
    }

    const content = fs.readFileSync(envFile, "utf-8");
    for (const rawLine of content.split("\n")) {
      const line = rawLine.trim();
      if (!line || line.startsWith("#")) continue;
      const eqIdx = line.indexOf("=");
      if (eqIdx < 0) continue;
      const key = line.slice(0, eqIdx).trim();
      let value = line.slice(eqIdx + 1).trim();
      if (
        (value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))
      ) {
        value = value.slice(1, -1);
      }
      if (typeof process !== "undefined" && process.env && !(key in process.env)) {
        process.env[key] = value;
      }
    }

    return { policyBaseDir: path.dirname(path.resolve(envFile)) };
  } catch {
    return { policyBaseDir: "" };
  }
}

export class YumiAgent {
  private readonly opts: YumiAgentOptions;
  private connectionCode: string | undefined;
  private edgeName: string;
  private policyBaseDir: string;
  private confirmationPolicyMemory: ConfirmationPolicy = {
    always_allow: [],
    force_confirm: [],
  };
  private dotEnvLoaded = false;

  private tools = new Map<string, RegisteredTool>();
  private wsSession: YumiWsSession | null = null;
  private stopRequested = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private inFlight = new Map<string, AbortController>();

  constructor(opts: YumiAgentOptions = {}) {
    this.opts = opts;
    this.connectionCode =
      opts.connectionCode ??
      getEnv().YUMI_CONNECTION_CODE ??
      getEnv().BRAIN_URL ??
      undefined;
    this.edgeName = defaultEdgeName(opts);
    this.policyBaseDir = "";
  }

  register(opts: RegisterOptions): void {
    if (!/^[a-zA-Z0-9_-]{1,64}$/.test(opts.name)) {
      throw new Error(
        `Tool name "${opts.name}" is invalid: use only letters, digits, '_' or '-' ` +
          `(max 64 chars). Model providers reject other function names.`
      );
    }
    const schema = buildToolSchema(opts);
    this.tools.set(opts.name, {
      schema,
      handler: opts.handler,
    });
  }

  runInBackground(): void {
    if (this.tools.size === 0) {
      console.log(`${LOG_PREFIX} Warning: no tools registered.`);
    }
    this.stopRequested = false;
    this.connectLoop().catch((err) => {
      console.error(`${LOG_PREFIX} Fatal connection error:`, err);
    });
  }

  stop(): void {
    this.stopRequested = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.cancelInFlight();
    if (this.wsSession) {
      try {
        this.wsSession.close();
      } catch {
        /* ignore */
      }
      this.wsSession = null;
    }
  }

  private canPersistPolicyToDisk(): boolean {
    return isNode() && !!this.policyBaseDir;
  }

  private confirmationPolicyPath(): string {
    const override = (getEnv().YUMI_TOOL_CONFIRMATION_PATH ?? "").trim();
    if (override && isNode()) {
      try {
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        const path = require("path") as typeof import("path");
        return path.resolve(override);
      } catch {
        return override;
      }
    }
    if (!this.policyBaseDir) return TOOL_CONFIRMATION_FILENAME;
    try {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const path = require("path") as typeof import("path");
      return path.join(this.policyBaseDir, TOOL_CONFIRMATION_FILENAME);
    } catch {
      return `${this.policyBaseDir}/${TOOL_CONFIRMATION_FILENAME}`;
    }
  }

  private loadConfirmationPolicy(): ConfirmationPolicy {
    if (this.canPersistPolicyToDisk()) {
      try {
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        const fs = require("fs") as typeof import("fs");
        const filePath = this.confirmationPolicyPath();
        if (fs.existsSync(filePath)) {
          const raw = JSON.parse(fs.readFileSync(filePath, "utf-8"));
          const aa = Array.isArray(raw.always_allow)
            ? raw.always_allow.filter(Boolean).map(String)
            : [];
          const fc = Array.isArray(raw.force_confirm)
            ? raw.force_confirm.filter(Boolean).map(String)
            : [];
          const pol: ConfirmationPolicy = { always_allow: aa, force_confirm: fc };
          this.confirmationPolicyMemory = pol;
          return pol;
        }
      } catch {
        /* fall through */
      }
    }
    return {
      always_allow: [...this.confirmationPolicyMemory.always_allow],
      force_confirm: [...this.confirmationPolicyMemory.force_confirm],
    };
  }

  private saveConfirmationPolicy(data: ConfirmationPolicy): void {
    this.confirmationPolicyMemory = {
      always_allow: [...(data.always_allow ?? [])],
      force_confirm: [...(data.force_confirm ?? [])],
    };
    if (!this.canPersistPolicyToDisk()) return;
    try {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const fs = require("fs") as typeof import("fs");
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const path = require("path") as typeof import("path");
      const filePath = this.confirmationPolicyPath();
      const dir = path.dirname(filePath);
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(
        filePath,
        JSON.stringify(
          {
            always_allow: this.confirmationPolicyMemory.always_allow,
            force_confirm: this.confirmationPolicyMemory.force_confirm,
          },
          null,
          2
        ),
        "utf-8"
      );
    } catch {
      /* ignore */
    }
  }

  private cancelInFlight(): void {
    for (const controller of this.inFlight.values()) {
      controller.abort();
    }
    this.inFlight.clear();
  }

  private refreshFromEnvAfterDotEnv(): void {
    this.connectionCode =
      this.opts.connectionCode ??
      getYumiEnv().YUMI_CONNECTION_CODE ??
      getYumiEnv().BRAIN_URL ??
      undefined;
    this.edgeName = defaultEdgeName(this.opts);
  }

  private async connectLoop(): Promise<void> {
    if (!this.dotEnvLoaded) {
      this.dotEnvLoaded = true;
      const { policyBaseDir } = await loadDotEnvFileIfNode(this.opts);
      this.policyBaseDir = policyBaseDir;
      this.refreshFromEnvAfterDotEnv();
    }

    let connection: ConnectionConfig;
    try {
      connection = await resolveConnection(this.connectionCode, this.edgeName);
    } catch (err) {
      console.error(`${LOG_PREFIX} Failed to resolve connection:`, err);
      return;
    }

    let reconnectDelay = 3;

    while (!this.stopRequested) {
      try {
        await this.runSession(connection);
        reconnectDelay = 3;
      } catch (err) {
        this.cancelInFlight();
        if (this.stopRequested) break;
        const waitMs = reconnectDelayMsWithJitter(reconnectDelay);
        console.log(
          `${LOG_PREFIX} Connection lost: ${err}. Reconnecting in ${(waitMs / 1000).toFixed(1)}s...`
        );
        await sleep(waitMs);
        reconnectDelay = Math.min(reconnectDelay * 2, 30);
      }
    }
  }

  private runSession(connection: ConnectionConfig): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      const wsUrl =
        connection.mode === "relay"
          ? relayEdgeWsUrl(connection)
          : connection.baseUrl;

      void openIsomorphicWebSocket(wsUrl, {
        onOpen: (session) => {
          this.wsSession = session;

          // buildToolSchema() already encoded require_confirmation from the
          // same opts, so the stored schema is the single source of truth.
          const toolSchemas = Array.from(this.tools.values()).map((t) => ({ ...t.schema }));

          const registerPayload: Record<string, unknown> = {
            type: "register",
            edge_name: this.edgeName,
            tools: toolSchemas,
            tool_confirmation_policy: this.loadConfirmationPolicy(),
          };
          if (connection.accessToken) {
            registerPayload.access_token = connection.accessToken;
          }

          session.send(JSON.stringify(registerPayload));
          console.log(
            `${LOG_PREFIX} Connected as [${this.edgeName}] with ${this.tools.size} tool(s).`
          );
          this.inFlight.clear();
        },
        onMessage: (text: string) => {
          let msg: Record<string, unknown>;
          try {
            msg = JSON.parse(text);
          } catch {
            return;
          }

          const msgType = msg.type as string | undefined;

          if (msgType === "persist_tool_confirmation_policy") {
            const aa = msg.always_allow;
            const fc = msg.force_confirm;
            if (Array.isArray(aa) && Array.isArray(fc)) {
              this.saveConfirmationPolicy({
                always_allow: aa.filter(Boolean).map(String),
                force_confirm: fc.filter(Boolean).map(String),
              });
            }
          } else if (msgType === "tool_call") {
            void this.handleToolCall(msg);
          } else if (msgType === "cancel") {
            const callId = msg.call_id as string;
            if (callId) {
              // Signal the running handler (cooperative — it must observe the
              // AbortSignal; JS can't force-stop an unwilling handler).
              this.inFlight.get(callId)?.abort();
              this.inFlight.delete(callId);
            }
          } else if (msgType === "register_warning") {
            const dropped = Array.isArray(msg.skipped_tools) ? msg.skipped_tools : [];
            console.warn(
              `${LOG_PREFIX} Server did not mount ${dropped.length} tool(s): ` +
                `${dropped.join(", ")} — ${msg.message ?? ""}`
            );
          } else if (msgType === "register_rejected") {
            // The server refused this edge_name (already in use). Stop — do NOT
            // reconnect, or it would just be rejected again.
            const reason = (msg.reason as string) || "edge_name already in use";
            console.error(`${LOG_PREFIX} Edge registration rejected by server: ${reason}`);
            this.stopRequested = true;
            this.wsSession?.close();
          }
        },
        onClose: () => {
          this.wsSession = null;
          if (this.stopRequested) {
            resolve();
          } else {
            reject(new Error("WebSocket closed"));
          }
        },
        onError: (err) => {
          this.wsSession = null;
          reject(err instanceof Error ? err : new Error(String(err)));
        },
      }).catch(reject);
    });
  }

  private async handleToolCall(msg: Record<string, unknown>): Promise<void> {
    const ws = this.wsSession;
    if (!ws) return;

    const toolName = (msg.name as string) ?? "";
    const rawArgs = (msg.arguments as Record<string, unknown>) ?? {};
    const callId = (msg.call_id as string) ?? "unknown";

    const tool = this.tools.get(toolName);
    if (!tool) {
      this.sendResult(ws, callId, `Error: Tool '${toolName}' is not registered on this edge.`, false);
      return;
    }

    const args = new ToolArguments(rawArgs);
    const controller = new AbortController();
    this.inFlight.set(callId, controller);

    let cancelled = false;
    let result: string;

    try {
      const handlerResult = tool.handler(args, controller.signal);
      const raw =
        handlerResult instanceof Promise ? await handlerResult : handlerResult;
      result = String(raw);
      if (controller.signal.aborted) {
        cancelled = true;
        result = `Cancelled: Tool '${toolName}' execution was cancelled by server.`;
      }
    } catch (err: unknown) {
      if (controller.signal.aborted || (err instanceof Error && err.message === "CANCELLED")) {
        cancelled = true;
        result = `Cancelled: Tool '${toolName}' execution was cancelled by server.`;
      } else {
        result = `Error executing tool '${toolName}': ${err}`;
      }
    } finally {
      this.inFlight.delete(callId);
    }

    this.sendResult(ws, callId, result, cancelled);
  }

  private sendResult(
    ws: YumiWsSession,
    callId: string,
    result: string,
    cancelled: boolean
  ): void {
    try {
      ws.send(
        JSON.stringify({
          type: "tool_result",
          call_id: callId,
          result,
          cancelled,
        })
      );
    } catch {
      /* ignore */
    }
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/** Base delay in seconds → milliseconds with ±500ms jitter (mitigates thundering herd on relay restarts). */
function reconnectDelayMsWithJitter(delaySeconds: number): number {
  const baseMs = delaySeconds * 1000;
  const jitter = Math.floor(Math.random() * 1001) - 500;
  return Math.max(1000, baseMs + jitter);
}
