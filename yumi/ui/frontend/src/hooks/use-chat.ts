import { useCallback, useEffect, useRef, useState } from "react"
import { toast } from "sonner"
import { ApiError, api, streamChat, synthesizeSpeech } from "@/lib/api"
import type { ChatEvent, ChatMessage, Role, ToolDecision } from "@/lib/types"
import { useApp } from "@/store/app"

export interface ToolEvent {
  id: number
  status: string
  content: string
}

export interface PendingFile {
  path: string
  name: string
  isImage: boolean
  sizeLabel?: string
}

export interface PendingConfirm {
  call_id: string
  tool_name: string
  arguments: Record<string, unknown>
}

let toolSeq = 0

function buildPrompt(prompt: string, files: PendingFile[]): { display: string; actual: string } {
  if (!files.length) return { display: prompt, actual: prompt }
  const imgs = files.filter((f) => f.isImage).map((f) => f.path)
  const docs = files.filter((f) => !f.isImage).map((f) => f.path)
  const parts: string[] = []
  if (imgs.length)
    parts.push(
      "The following images are saved on the Yumi server and will be inlined for the vision model. " +
        "Please view them and describe what you see:\n" +
        imgs.join("\n"),
    )
  if (docs.length)
    parts.push(
      "The following files are saved on the Yumi server. Use the read_file tool to read each path " +
        "in order and answer the user's question:\n" +
        docs.join("\n"),
    )
  const prefix = parts.join("\n\n")
  const display = prompt || "Please analyze the uploaded file(s)"
  const actual = prefix ? `${prefix}\n\n${prompt}`.trim() : prompt
  return { display, actual }
}

// Sentinels for DB rows that only persist tool_calls / tool results for LLM
// replay. They are not end-user chat and must never render (see the backend
// constants YUMI_V1_TOOL_CALLS / YUMI_V1_TOOL_RESULT).
const REPLAY_PREFIXES = ["__yumi:v1:tc__", "__yumi:v1:tool__"]

function isReplayArtifact(content: string): boolean {
  const c = content.trimStart()
  return REPLAY_PREFIXES.some((p) => c.startsWith(p))
}

/** Drop replay rows, de-duplicate by id, collapse back-to-back identical user rows. */
function normalize(rows: { id: string; role: string; content: string; thought?: string }[]): ChatMessage[] {
  const seen = new Set<string>()
  const out: ChatMessage[] = []
  for (const m of rows) {
    if (m.role !== "user" && m.role !== "assistant") continue
    const content = m.content || ""
    if (!content.trim() || isReplayArtifact(content)) continue
    if (m.id && seen.has(m.id)) continue
    if (m.id) seen.add(m.id)
    const prev = out[out.length - 1]
    if (m.role === "user" && prev?.role === "user" && prev.content.trim() === content.trim()) continue
    out.push({ id: m.id, role: m.role as Role, content, thought: m.thought })
  }
  return out
}

export function useChat(sessionId: string | null) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [streaming, setStreaming] = useState(false)
  const [streamContent, setStreamContent] = useState("")
  const [streamThought, setStreamThought] = useState("")
  const [toolEvents, setToolEvents] = useState<ToolEvent[]>([])
  const [error, setError] = useState<string | null>(null)
  const [confirm, setConfirm] = useState<PendingConfirm | null>(null)
  const [loading, setLoading] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const voiceReplies = useApp((s) => s.voiceReplies)

  const reload = useCallback(async (sid: string) => {
    try {
      setMessages(normalize(await api.listMessages(sid)))
    } catch {
      setMessages([])
    }
  }, [])

  useEffect(() => {
    setStreamContent("")
    setStreamThought("")
    setToolEvents([])
    setError(null)
    setConfirm(null)
    setStreaming(false)
    if (sessionId) {
      setLoading(true)
      reload(sessionId).finally(() => setLoading(false))
    } else {
      setMessages([])
    }
  }, [sessionId, reload])

  // Long-lived timer-event stream: proactive assistant messages for the open session.
  const sidRef = useRef(sessionId)
  sidRef.current = sessionId
  useEffect(() => {
    const ctrl = new AbortController()
    ;(async () => {
      try {
        const resp = await fetch("/timer-events", { signal: ctrl.signal })
        if (!resp.body) return
        const reader = resp.body.getReader()
        const dec = new TextDecoder()
        let buf = ""
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buf += dec.decode(value, { stream: true })
          let nl: number
          while ((nl = buf.indexOf("\n")) >= 0) {
            const line = buf.slice(0, nl).trim()
            buf = buf.slice(nl + 1)
            if (!line) continue
            try {
              const data = JSON.parse(line)
              if (data.type === "heartbeat") continue
              if (data.session_id && data.session_id === sidRef.current) {
                const text = (data.events || [])
                  .filter((e: { type: string }) => e.type === "text")
                  .map((e: { content: string }) => e.content)
                  .join("")
                  .trim()
                const display = text ? (text.startsWith("⏰") ? text : `⏰ ${text}`) : `⏰ ${data.description || "Timer"}`
                setMessages((m) => [...m, { id: `timer-${Date.now()}`, role: "assistant", content: display }])
              }
            } catch {
              // ignore malformed line
            }
          }
        }
      } catch {
        // stream aborted or server gone — silent (page may be navigating away)
      }
    })()
    return () => ctrl.abort()
  }, [])

  const send = useCallback(
    async (text: string, opts: { think: boolean; files: PendingFile[] }) => {
      const sid = sessionId
      if (!sid || streaming) return
      const prompt = text.trim()
      if (!prompt && !opts.files.length) return

      const { display, actual } = buildPrompt(prompt, opts.files)
      setMessages((m) => [...m, { id: `local-${Date.now()}`, role: "user", content: display }])
      setError(null)
      setStreaming(true)
      setStreamContent("")
      setStreamThought("")
      setToolEvents([])

      const ctrl = new AbortController()
      abortRef.current = ctrl
      let acc = ""
      let accThought = ""
      try {
        await streamChat(
          { prompt: actual, session_id: sid, think: opts.think },
          {
            signal: ctrl.signal,
            onEvent: (evt: ChatEvent) => {
              switch (evt.type) {
                case "text":
                  acc += evt.content
                  setStreamContent(acc)
                  break
                case "thought":
                  if (opts.think) {
                    accThought += evt.content
                    setStreamThought(accThought)
                  }
                  break
                case "tool_status":
                  setToolEvents((te) => [...te, { id: ++toolSeq, status: evt.status, content: evt.content }])
                  break
                case "tool_confirmation":
                  setConfirm({
                    call_id: evt.call_id,
                    tool_name: evt.tool_name,
                    arguments: evt.arguments || {},
                  })
                  break
                case "error":
                  setError(evt.content)
                  break
              }
            },
          },
        )
        await reload(sid)
        if (voiceReplies && acc.trim()) {
          synthesizeSpeech(acc.trim(), sid)
            .then((url) => {
              const audio = new Audio(url)
              audio.onended = () => URL.revokeObjectURL(url)
              void audio.play().catch(() => undefined)
            })
            .catch(() => undefined)
        }
      } catch (e) {
        const aborted = e instanceof DOMException && e.name === "AbortError"
        if (!aborted) setError(e instanceof ApiError ? e.message : String(e))
        if (acc.trim()) {
          setMessages((m) => [
            ...m,
            { id: `local-a-${Date.now()}`, role: "assistant", content: acc, thought: accThought },
          ])
        }
      } finally {
        setStreaming(false)
        setStreamContent("")
        setStreamThought("")
        setToolEvents([])
        setConfirm(null)
        abortRef.current = null
      }
    },
    [sessionId, streaming, reload, voiceReplies],
  )

  const confirmDecision = useCallback(
    async (decision: ToolDecision) => {
      const c = confirm
      if (!c) return
      setConfirm(null)
      try {
        await api.confirmTool(c.call_id, decision)
      } catch {
        toast.error("Failed to send the tool decision")
      }
    },
    [confirm],
  )

  const stop = useCallback(() => abortRef.current?.abort(), [])

  return {
    messages,
    streaming,
    streamContent,
    streamThought,
    toolEvents,
    error,
    confirm,
    loading,
    send,
    stop,
    confirmDecision,
    clearError: () => setError(null),
  }
}
