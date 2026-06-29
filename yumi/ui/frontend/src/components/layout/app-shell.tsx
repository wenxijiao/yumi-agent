import { Suspense } from "react"
import { Outlet } from "react-router-dom"
import { TriangleAlert } from "lucide-react"
import { NavRail } from "./nav-rail"
import { CommandPalette } from "@/components/command-palette"
import { useHealth } from "@/hooks/queries"

function PageFallback() {
  return <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">Loading…</div>
}

export function AppShell() {
  const health = useHealth()
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background text-foreground">
      <NavRail />
      <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
        {health.isError && (
          <div className="flex items-center gap-2 border-b border-destructive/30 bg-destructive/10 px-4 py-2 text-sm text-destructive">
            <TriangleAlert className="size-4 shrink-0" />
            <span>
              Can&apos;t reach the Yumi server — is <code className="rounded bg-destructive/15 px-1 font-mono">yumi --server</code> running?
            </span>
          </div>
        )}
        <Suspense fallback={<PageFallback />}>
          <Outlet />
        </Suspense>
      </main>
      <CommandPalette />
    </div>
  )
}
