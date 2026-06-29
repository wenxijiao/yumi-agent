// Types mirroring the Yumi core HTTP API (see docs/HTTP_API.md).

export type Role = "user" | "assistant" | "system" | "tool"

export interface ChatMessage {
  id: string
  role: Role
  content: string
  thought?: string
}

export interface Session {
  session_id: string
  title: string
  status: string
  is_pinned: boolean
  message_count: number
  created_at?: string
  updated_at?: string
  last_message_at?: string
}

// One line of the POST /chat NDJSON stream.
export type ChatEvent =
  | { type: "text"; content: string }
  | { type: "thought"; content: string }
  | { type: "tool_status"; status: "running" | "success" | "error" | "denied"; content: string }
  | {
      type: "tool_confirmation"
      call_id: string
      tool_name: string
      full_tool_name?: string
      arguments: Record<string, unknown>
    }
  | { type: "error"; content: string; code?: string }

export type ToolDecision = "allow" | "deny" | "always_allow"

export interface ServerTool {
  name: string
  description: string
  disabled: boolean
  require_confirmation: boolean
}

export interface EdgeTool {
  name: string
  full_name: string
  description: string
  disabled: boolean
  require_confirmation: boolean
}

export interface EdgeDevice {
  edge_name: string
  online: boolean
  tools: EdgeTool[]
}

export interface ToolsResponse {
  server_tools: ServerTool[]
  edge_devices: EdgeDevice[]
  disabled_tools: string[]
  confirmation_tools: string[]
  always_allowed_tools: string[]
}

export interface Trace {
  id?: string
  ts: string
  session_id: string
  tool_name: string
  display_name?: string
  kind?: string
  edge_name?: string | null
  status: string
  duration_ms: number
  arguments?: unknown
  result_preview?: string
}

export interface TopologyEdge {
  edge_name: string
  online: boolean
  tool_count: number
}

export interface Topology {
  server: { id: string; label: string; role: string }
  local_tool_count: number
  edges: TopologyEdge[]
}

export interface Timer {
  timer_id: string
  description: string
  session_id?: string
  owner_id?: string
  fire_at?: string
  [k: string]: unknown
}

export interface ModelConfig {
  chat_provider: string
  chat_model: string
  embedding_provider: string
  embedding_model: string
  memory_max_recent_messages: number
  memory_max_related_messages: number
  chat_append_current_time?: boolean
  chat_append_tool_use_instruction?: boolean
  edge_tools_enable_dynamic_routing?: boolean
  edge_tools_retrieval_limit?: number
  stt_provider?: string
  stt_backend?: string
  stt_model?: string
  stt_language?: string
  tts_provider?: string
  tts_voice?: string
  tts_model?: string
  tts_language?: string
  openai_api_key_saved?: boolean
  gemini_api_key_saved?: boolean
  claude_api_key_saved?: boolean
  deepseek_api_key_saved?: boolean
  grok_api_key_saved?: boolean
  tts_api_key_saved?: boolean
  openai_base_url?: string
  deepseek_base_url?: string
  grok_base_url?: string
  [k: string]: unknown
}

// ── /stats payload ──

export interface StatModelUsage {
  model: string
  turns: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
}

export interface StatDailyUsage {
  day: string
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  turns: number
}

export interface Stats {
  generated_at: string
  tools: {
    server_total: number
    server_enabled: number
    server_disabled: number
    require_confirmation: number
    edge_total: number
    edge_devices: number
    edge_online: number
    total: number
  }
  sessions: {
    active: number
    total_messages: number
    total_turns: number
    avg_messages: number
  }
  tool_calls: {
    total: number
    edge_calls: number
    by_status: Record<string, number>
    top_tools: { name: string; count: number }[]
    avg_duration_ms: number
  }
  tokens: {
    total: number
    prompt: number
    completion: number
    turns: number
    by_model: StatModelUsage[]
    daily: StatDailyUsage[]
  }
}

export interface SystemPrompt {
  system_prompt: string
  is_default: boolean
}

export interface SessionPrompt {
  session_id: string
  system_prompt: string
  is_custom: boolean
}

export interface SearchResult {
  id: string
  session_id: string
  role: Role
  content: string
  thought?: string
  timestamp?: string
  score?: number
  [k: string]: unknown
}
