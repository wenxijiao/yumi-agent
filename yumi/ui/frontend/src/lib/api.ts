import type {
  ChatEvent,
  ModelConfig,
  Observability,
  SearchResult,
  Session,
  SessionPrompt,
  Stats,
  SystemPrompt,
  Timer,
  Topology,
  Trace,
  ToolDecision,
  ToolsResponse,
} from "./types"

// Same-origin: the SPA is served by the core server, and the API lives at the
// server root. In dev, Vite proxies these paths to `yumi --server`.
const BASE = ""

export class ApiError extends Error {
  status: number
  code?: string
  hint?: string
  constructor(message: string, status: number, code?: string, hint?: string) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.code = code
    this.hint = hint
  }
}

function parseDetail(body: unknown, fallback: string): { message: string; code?: string; hint?: string } {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === "string") return { message: detail }
    if (Array.isArray(detail)) return { message: detail.map((d) => JSON.stringify(d)).join("; ") }
    if (detail && typeof detail === "object") {
      const d = detail as Record<string, unknown>
      return {
        message: String(d.message ?? d.code ?? fallback),
        code: d.code ? String(d.code) : undefined,
        hint: d.hint ? String(d.hint) : undefined,
      }
    }
  }
  return { message: fallback }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  let resp: Response
  try {
    resp = await fetch(`${BASE}${path}`, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch (e) {
    throw new ApiError(`Cannot reach the Yumi server. Is it running? (${String(e)})`, 0)
  }
  const text = await resp.text()
  let json: unknown = undefined
  if (text) {
    try {
      json = JSON.parse(text)
    } catch {
      json = undefined
    }
  }
  if (!resp.ok) {
    const { message, code, hint } = parseDetail(json, `${resp.status} ${resp.statusText}`)
    throw new ApiError(message, resp.status, code, hint)
  }
  return (json ?? {}) as T
}

export const api = {
  health: () => request<{ status: string }>("GET", "/health"),

  // ── sessions ──
  listSessions: (status = "active") =>
    request<{ sessions: Session[] }>("GET", `/memory/sessions?status=${status}`).then((r) =>
      (r.sessions || []).map((s) => ({ ...s, title: s.title || "New chat" })),
    ),
  createSession: (title?: string) =>
    request<{ session: Session }>("POST", "/memory/sessions", title ? { title } : {}).then((r) => r.session),
  updateSession: (id: string, patch: Partial<Pick<Session, "title" | "is_pinned" | "status">>) =>
    request<{ session: Session }>("PUT", `/memory/sessions/${id}`, patch).then((r) => r.session),
  deleteSession: (id: string) => request("PUT", `/memory/sessions/${id}`, { status: "deleted" }),

  // ── messages ──
  listMessages: (sessionId: string, limit = 200) =>
    request<{ messages: { id: string; role: string; content: string; thought?: string }[] }>(
      "GET",
      `/memory/messages?session_id=${encodeURIComponent(sessionId)}&limit=${limit}`,
    ).then((r) => r.messages || []),
  clearSession: (sessionId: string) => request("POST", `/clear?session_id=${encodeURIComponent(sessionId)}`),
  searchMemory: (query: string, sessionId?: string, limit = 30) => {
    const q = new URLSearchParams({ query, limit: String(limit) })
    if (sessionId) q.set("session_id", sessionId)
    return request<{ messages: SearchResult[] }>("GET", `/memory/search?${q.toString()}`).then(
      (r) => r.messages || [],
    )
  },

  // ── tools ──
  tools: () => request<ToolsResponse>("GET", "/tools"),
  toggleTool: (tool_name: string, disabled: boolean) =>
    request("POST", "/tools/toggle", { tool_name, disabled }),
  setToolConfirmation: (tool_name: string, require_confirmation: boolean) =>
    request("POST", "/tools/set-confirmation", { tool_name, require_confirmation }),
  confirmTool: (call_id: string, decision: ToolDecision) =>
    request("POST", "/tools/confirm", { call_id, decision }),

  // ── monitor ──
  topology: () => request<Topology>("GET", "/monitor/topology"),
  traces: (sessionId?: string, limit = 200) => {
    const q = new URLSearchParams({ limit: String(limit) })
    if (sessionId) q.set("session_id", sessionId)
    return request<{ traces: Trace[] }>("GET", `/monitor/traces?${q.toString()}`).then((r) => r.traces || [])
  },

  // ── stats ──
  stats: () => request<Stats>("GET", "/stats"),

  // ── debug / observability ──
  observability: (limit = 50) => request<Observability>("GET", `/debug/observability?limit=${limit}`),

  // ── timers ──
  timers: () => request<{ timers: Timer[] }>("GET", "/timers").then((r) => r.timers || []),
  cancelTimer: (id: string) => request("DELETE", `/timers/${encodeURIComponent(id)}`),

  // ── config ──
  getModelConfig: () => request<ModelConfig>("GET", "/config/model"),
  updateModelConfig: (patch: Record<string, unknown>) =>
    request<ModelConfig>("PUT", "/config/model", patch),
  getUiPrefs: () => request<{ dark_mode: boolean }>("GET", "/config/ui"),
  setUiPrefs: (dark_mode: boolean) => request("PUT", "/config/ui", { dark_mode }),
  getSystemPrompt: () => request<SystemPrompt>("GET", "/config/system-prompt"),
  setSystemPrompt: (system_prompt: string) =>
    request<SystemPrompt>("PUT", "/config/system-prompt", { system_prompt }),
  resetSystemPrompt: () => request<SystemPrompt>("DELETE", "/config/system-prompt"),
  getSessionPrompt: (id: string) => request<SessionPrompt>("GET", `/config/session-prompt/${id}`),
  setSessionPrompt: (id: string, system_prompt: string) =>
    request<SessionPrompt>("PUT", `/config/session-prompt/${id}`, { system_prompt }),
  resetSessionPrompt: (id: string) => request("DELETE", `/config/session-prompt/${id}`),

  // ── uploads & speech ──
  upload: (sessionId: string, filename: string, contentBase64: string) =>
    request<{ path: string; is_image?: boolean; id?: string }>("POST", "/uploads", {
      session_id: sessionId,
      filename,
      content_base64: contentBase64,
    }),
  transcribe: (sessionId: string, filename: string, contentBase64: string, language?: string) =>
    request<{ text: string; language?: string; duration_seconds?: number }>("POST", "/stt/transcribe", {
      session_id: sessionId,
      filename,
      content_base64: contentBase64,
      language,
    }),
}

/** Synthesize speech; returns an object URL for an <audio> element (caller revokes it). */
export async function synthesizeSpeech(text: string, sessionId = "default", voice?: string): Promise<string> {
  const resp = await fetch(`${BASE}/tts/synthesize`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, session_id: sessionId, voice }),
  })
  if (!resp.ok) {
    const body = await resp.json().catch(() => undefined)
    const { message } = parseDetail(body, `TTS failed (${resp.status})`)
    throw new ApiError(message, resp.status)
  }
  const blob = await resp.blob()
  return URL.createObjectURL(blob)
}

export interface ChatStreamHandlers {
  onEvent: (event: ChatEvent) => void
  signal?: AbortSignal
}

/**
 * POST /chat and dispatch each NDJSON line as a ChatEvent.
 * Resolves when the stream ends; rejects on transport/HTTP error (not on
 * in-stream `error` events, which are delivered via onEvent).
 */
export async function streamChat(
  body: { prompt: string; session_id: string; think: boolean },
  { onEvent, signal }: ChatStreamHandlers,
): Promise<void> {
  const resp = await fetch(`${BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  })
  if (!resp.ok || !resp.body) {
    const text = await resp.text().catch(() => "")
    let detail: unknown
    try {
      detail = JSON.parse(text)
    } catch {
      detail = undefined
    }
    const { message } = parseDetail(detail, `${resp.status} ${resp.statusText}`)
    throw new ApiError(message, resp.status)
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let nl: number
    while ((nl = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, nl).trim()
      buffer = buffer.slice(nl + 1)
      if (!line) continue
      try {
        onEvent(JSON.parse(line) as ChatEvent)
      } catch {
        // ignore malformed line
      }
    }
  }
  const tail = buffer.trim()
  if (tail) {
    try {
      onEvent(JSON.parse(tail) as ChatEvent)
    } catch {
      // ignore
    }
  }
}
