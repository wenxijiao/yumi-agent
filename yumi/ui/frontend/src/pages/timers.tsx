import { useState } from "react"
import { Clock, AlarmClock, Trash2, RefreshCw } from "lucide-react"
import { toast } from "sonner"
import { useQueryClient } from "@tanstack/react-query"
import { PageHeader, PageBody } from "@/components/layout/page"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Card, CardContent } from "@/components/ui/card"
import { useTimers, qk } from "@/hooks/queries"
import { api } from "@/lib/api"
import { timeAgo } from "@/lib/format"
import { cn } from "@/lib/utils"
import type { Timer } from "@/lib/types"

// Returns a human-readable relative label for fire_at.
// If the timestamp is in the future returns "in Xm" etc.; otherwise falls
// back to timeAgo (e.g. "3m ago").
function fireAtRelative(iso?: string): { label: string; isFuture: boolean } {
  if (!iso) return { label: "No schedule", isFuture: false }
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return { label: iso, isFuture: false }
  const diff = then - Date.now()
  if (diff > 0) {
    const sec = Math.round(diff / 1000)
    if (sec < 60) return { label: `in ${sec}s`, isFuture: true }
    const min = Math.round(sec / 60)
    if (min < 60) return { label: `in ${min}m`, isFuture: true }
    const hr = Math.round(min / 60)
    if (hr < 24) return { label: `in ${hr}h`, isFuture: true }
    return { label: `in ${Math.round(hr / 24)}d`, isFuture: true }
  }
  return { label: timeAgo(iso), isFuture: false }
}

function fireAtReadable(iso?: string): string {
  if (!iso) return ""
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ""
  return d.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

function TimerRow({ timer }: { timer: Timer }) {
  const qc = useQueryClient()
  const [cancelling, setCancelling] = useState(false)

  const { label, isFuture } = fireAtRelative(timer.fire_at)
  const readable = fireAtReadable(timer.fire_at)

  async function handleCancel() {
    setCancelling(true)
    try {
      await api.cancelTimer(timer.timer_id)
      await qc.invalidateQueries({ queryKey: qk.timers })
      toast.success("Timer cancelled")
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to cancel timer")
    } finally {
      setCancelling(false)
    }
  }

  return (
    <Card className="shadow-sm">
      <CardContent className="flex items-center gap-4 p-4">
        {/* Icon */}
        <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">
          <AlarmClock className="size-5" />
        </div>

        {/* Body */}
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium text-foreground">{timer.description}</p>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            {timer.fire_at && (
              <span
                className={cn(
                  "text-xs font-medium",
                  isFuture ? "text-primary" : "text-muted-foreground",
                )}
              >
                {label}
                {readable && (
                  <span className="ml-1 font-normal text-muted-foreground">· {readable}</span>
                )}
              </span>
            )}
            {timer.session_id && (
              <Badge variant="muted" className="font-mono">
                {timer.session_id.slice(0, 8)}
              </Badge>
            )}
          </div>
        </div>

        {/* Cancel */}
        <Button
          variant="destructive"
          size="icon-sm"
          onClick={handleCancel}
          disabled={cancelling}
          aria-label="Cancel timer"
        >
          <Trash2 />
        </Button>
      </CardContent>
    </Card>
  )
}

function TimerSkeleton() {
  return (
    <Card className="shadow-sm">
      <CardContent className="flex items-center gap-4 p-4">
        <Skeleton className="size-10 shrink-0 rounded-xl" />
        <div className="flex-1 space-y-2">
          <Skeleton className="h-4 w-3/5" />
          <Skeleton className="h-3 w-1/4" />
        </div>
        <Skeleton className="size-8 rounded-lg" />
      </CardContent>
    </Card>
  )
}

export function TimersPage() {
  const { data: timers, isLoading, refetch } = useTimers(10000)

  return (
    <>
      <PageHeader
        title="Schedules"
        description="Active timers and proactive reminders."
        icon={Clock}
        actions={
          <Button variant="outline" size="sm" onClick={() => void refetch()}>
            <RefreshCw />
            Refresh
          </Button>
        }
      />

      <PageBody>
        {isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 4 }).map((_, i) => (
              <TimerSkeleton key={i} />
            ))}
          </div>
        ) : !timers?.length ? (
          <div className="flex flex-col items-center justify-center gap-3 py-24 text-center">
            <div className="flex size-16 items-center justify-center rounded-2xl bg-muted">
              <Clock className="size-8 text-muted-foreground" />
            </div>
            <p className="text-base font-semibold tracking-tight text-foreground">
              No active timers
            </p>
            <p className="max-w-xs text-sm text-muted-foreground">
              Ask Yumi to remind you about something and it will appear here.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {timers.map((t) => (
              <TimerRow key={t.timer_id} timer={t} />
            ))}
          </div>
        )}
      </PageBody>
    </>
  )
}
