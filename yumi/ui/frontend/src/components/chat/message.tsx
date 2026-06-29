import { useState } from "react"
import { Brain, Check, ChevronRight, Copy, Sparkles } from "lucide-react"
import { cn } from "@/lib/utils"
import type { ChatMessage } from "@/lib/types"
import { Markdown } from "./markdown"

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      onClick={() => {
        navigator.clipboard.writeText(text).then(() => {
          setCopied(true)
          setTimeout(() => setCopied(false), 1500)
        })
      }}
      className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-xs text-muted-foreground opacity-0 transition hover:bg-accent hover:text-foreground group-hover:opacity-100"
    >
      {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
      {copied ? "Copied" : "Copy"}
    </button>
  )
}

function Thinking({ text, streaming }: { text: string; streaming?: boolean }) {
  const [open, setOpen] = useState(false)
  if (!text) return null
  return (
    <div className="mb-2 overflow-hidden rounded-lg border border-border/70 bg-muted/40">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-1.5 px-3 py-2 text-xs font-medium text-muted-foreground transition hover:text-foreground"
      >
        <Brain className="size-3.5" />
        <span>{streaming ? "Thinking…" : "Reasoning"}</span>
        <ChevronRight className={cn("size-3.5 transition-transform", open && "rotate-90")} />
      </button>
      {open && (
        <div className="border-t border-border/70 px-3 py-2 text-[13px] leading-relaxed text-muted-foreground whitespace-pre-wrap">
          {text}
        </div>
      )}
    </div>
  )
}

export function AssistantAvatar() {
  return (
    <div className="flex size-7 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-primary to-[#6d4aff] text-white shadow-sm">
      <Sparkles className="size-4" />
    </div>
  )
}

export function MessageRow({
  message,
  streaming,
  children,
}: {
  message: ChatMessage
  streaming?: boolean
  children?: React.ReactNode
}) {
  if (message.role === "user") {
    return (
      <div className="group flex justify-end animate-in-up">
        <div className="flex max-w-[78%] flex-col items-end gap-1">
          <div className="whitespace-pre-wrap rounded-2xl rounded-br-md bg-primary/12 px-4 py-2.5 text-[15px] leading-relaxed text-foreground">
            {message.content}
          </div>
          <CopyButton text={message.content} />
        </div>
      </div>
    )
  }

  return (
    <div className="group flex gap-3 animate-in-up">
      <AssistantAvatar />
      <div className="min-w-0 flex-1 pt-0.5">
        {message.thought ? <Thinking text={message.thought} streaming={streaming} /> : null}
        {children}
        {message.content ? <Markdown content={message.content} /> : null}
        {streaming && message.content && (
          <span className="ml-0.5 inline-block h-4 w-[2px] translate-y-0.5 bg-primary animate-caret" />
        )}
        {!streaming && message.content ? (
          <div className="mt-1 -ml-1.5">
            <CopyButton text={message.content} />
          </div>
        ) : null}
      </div>
    </div>
  )
}
