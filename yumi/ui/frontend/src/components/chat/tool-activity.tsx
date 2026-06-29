import { Check, Loader2, ShieldAlert, Wrench, X } from "lucide-react"
import { cn } from "@/lib/utils"
import type { ToolEvent } from "@/hooks/use-chat"

const ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  running: Loader2,
  success: Check,
  error: X,
  denied: ShieldAlert,
}

const COLORS: Record<string, string> = {
  running: "text-primary",
  success: "text-success",
  error: "text-destructive",
  denied: "text-warning",
}

export function ToolActivity({ events }: { events: ToolEvent[] }) {
  if (!events.length) return null
  return (
    <div className="mb-2 space-y-1.5 rounded-xl border border-border/70 bg-muted/30 p-2.5">
      <div className="flex items-center gap-1.5 px-0.5 text-xs font-medium text-muted-foreground">
        <Wrench className="size-3.5" />
        Tool activity
      </div>
      {events.map((e) => {
        const Icon = ICONS[e.status] ?? Wrench
        return (
          <div key={e.id} className="flex items-start gap-2 px-0.5 text-[13px] text-foreground/90">
            <Icon className={cn("mt-0.5 size-3.5 shrink-0", COLORS[e.status], e.status === "running" && "animate-spin")} />
            <span className="min-w-0 break-words">{e.content}</span>
          </div>
        )
      })}
    </div>
  )
}
