import { ShieldQuestion } from "lucide-react"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import type { PendingConfirm } from "@/hooks/use-chat"
import type { ToolDecision } from "@/lib/types"

export function ConfirmDialog({
  confirm,
  onDecision,
}: {
  confirm: PendingConfirm | null
  onDecision: (d: ToolDecision) => void
}) {
  const open = !!confirm
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onDecision("deny")}>
      <DialogContent hideClose className="max-w-md">
        <DialogHeader>
          <div className="mb-1 flex size-10 items-center justify-center rounded-xl bg-warning/15 text-warning">
            <ShieldQuestion className="size-5" />
          </div>
          <DialogTitle>Allow this tool to run?</DialogTitle>
          <DialogDescription>
            Yumi wants to run <span className="font-medium text-foreground">{confirm?.tool_name}</span>. Review the
            arguments before allowing.
          </DialogDescription>
        </DialogHeader>
        {confirm && (
          <pre className="max-h-56 overflow-auto rounded-lg border border-border bg-muted/40 p-3 text-xs leading-relaxed text-foreground/90">
            {JSON.stringify(confirm.arguments, null, 2)}
          </pre>
        )}
        <div className="flex flex-col gap-2 sm:flex-row sm:justify-between">
          <Button variant="ghost" onClick={() => onDecision("deny")}>
            Deny
          </Button>
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => onDecision("always_allow")}>
              Always allow
            </Button>
            <Button onClick={() => onDecision("allow")}>Allow once</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
