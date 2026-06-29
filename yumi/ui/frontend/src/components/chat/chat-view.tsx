import { useEffect, useLayoutEffect, useRef, useState } from "react"
import { useQueryClient } from "@tanstack/react-query"
import { AlertTriangle, Lightbulb, PanelLeft, PanelLeftClose, Pin, PinOff, Sparkles, X } from "lucide-react"
import { api } from "@/lib/api"
import { qk, useSessions } from "@/hooks/queries"
import { useChat } from "@/hooks/use-chat"
import { useApp } from "@/store/app"
import { Button } from "@/components/ui/button"
import { SimpleTooltip } from "@/components/ui/tooltip"
import { MessageRow } from "./message"
import { ToolActivity } from "./tool-activity"
import { Composer } from "./composer"
import { ConfirmDialog } from "./confirm-dialog"

const SUGGESTIONS = [
  "What can you help me with?",
  "Summarize my recent notes",
  "Set a timer for 10 minutes",
  "What tools do you have access to?",
]

export function ChatView({ sessionId }: { sessionId: string }) {
  const chat = useChat(sessionId)
  const { data: sessions = [] } = useSessions()
  const qc = useQueryClient()
  const sidebarCollapsed = useApp((s) => s.chatSidebarCollapsed)
  const toggleSidebar = useApp((s) => s.toggleChatSidebar)
  const [think, setThink] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const session = sessions.find((s) => s.session_id === sessionId)

  const atBottomRef = useRef(true)
  const onScroll = () => {
    const el = scrollRef.current
    if (!el) return
    atBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 160
  }
  useLayoutEffect(() => {
    const el = scrollRef.current
    if (el && atBottomRef.current) el.scrollTop = el.scrollHeight
  }, [chat.messages, chat.streamContent, chat.streamThought, chat.toolEvents])

  useEffect(() => {
    atBottomRef.current = true
  }, [sessionId])

  const togglePin = async () => {
    if (!session) return
    await api.updateSession(session.session_id, { is_pinned: !session.is_pinned }).catch(() => undefined)
    qc.invalidateQueries({ queryKey: qk.sessions })
  }

  const showEmpty = !chat.loading && chat.messages.length === 0 && !chat.streaming

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <header className="flex items-center gap-2 border-b border-border px-4 py-3">
        <SimpleTooltip label={sidebarCollapsed ? "Show chats" : "Hide chats"}>
          <Button variant="ghost" size="icon-sm" onClick={toggleSidebar}>
            {sidebarCollapsed ? <PanelLeft className="size-4" /> : <PanelLeftClose className="size-4" />}
          </Button>
        </SimpleTooltip>
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-sm font-semibold">{session?.title || "New chat"}</h2>
        </div>
        {session && (
          <SimpleTooltip label={session.is_pinned ? "Unpin" : "Pin"}>
            <Button variant="ghost" size="icon-sm" onClick={togglePin}>
              {session.is_pinned ? <PinOff className="size-4" /> : <Pin className="size-4" />}
            </Button>
          </SimpleTooltip>
        )}
      </header>

      <div ref={scrollRef} onScroll={onScroll} className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl px-4 py-6">
          {showEmpty ? (
            <EmptyState onPick={(t) => chat.send(t, { think, files: [] })} />
          ) : (
            <div className="space-y-6">
              {chat.messages.map((m) => (
                <MessageRow key={m.id} message={m} />
              ))}

              {chat.streaming && (
                <MessageRow
                  streaming
                  message={{
                    id: "streaming",
                    role: "assistant",
                    content: chat.streamContent,
                    thought: chat.streamThought,
                  }}
                >
                  <ToolActivity events={chat.toolEvents} />
                  {!chat.streamContent && !chat.streamThought && chat.toolEvents.length === 0 && (
                    <ThinkingDots />
                  )}
                </MessageRow>
              )}
            </div>
          )}

          {chat.error && (
            <div className="mt-4 flex items-start gap-2 rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
              <AlertTriangle className="mt-0.5 size-4 shrink-0" />
              <span className="min-w-0 flex-1">{chat.error}</span>
              <button onClick={chat.clearError} className="rounded p-0.5 hover:bg-destructive/15">
                <X className="size-4" />
              </button>
            </div>
          )}
        </div>
      </div>

      <Composer
        sessionId={sessionId}
        streaming={chat.streaming}
        think={think}
        onToggleThink={() => setThink((t) => !t)}
        onSend={(text, files) => chat.send(text, { think, files })}
        onStop={chat.stop}
      />

      <ConfirmDialog confirm={chat.confirm} onDecision={chat.confirmDecision} />
    </div>
  )
}

function ThinkingDots() {
  return (
    <div className="flex items-center gap-1 py-1">
      {[0, 1, 2].map((i) => (
        <span
          key={i}
          className="size-1.5 animate-bounce rounded-full bg-muted-foreground/60"
          style={{ animationDelay: `${i * 0.15}s` }}
        />
      ))}
    </div>
  )
}

function EmptyState({ onPick }: { onPick: (text: string) => void }) {
  return (
    <div className="flex min-h-[55vh] flex-col items-center justify-center text-center">
      <div className="brand-glow mb-5 flex size-16 items-center justify-center rounded-2xl bg-gradient-to-br from-primary to-[#6d4aff] text-white shadow-xl shadow-primary/25">
        <Sparkles className="size-8" />
      </div>
      <h1 className="text-2xl font-semibold tracking-tight">How can I help?</h1>
      <p className="mt-2 max-w-md text-sm text-muted-foreground">
        Chat with your agent, attach files, or speak — Yumi can use its tools to get things done.
      </p>
      <div className="mt-7 grid w-full max-w-lg grid-cols-1 gap-2 sm:grid-cols-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            onClick={() => onPick(s)}
            className="flex items-center gap-2 rounded-xl border border-border bg-card px-3.5 py-3 text-left text-sm text-foreground/90 transition hover:border-primary/40 hover:bg-accent"
          >
            <Lightbulb className="size-4 shrink-0 text-primary" />
            <span className="truncate">{s}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
