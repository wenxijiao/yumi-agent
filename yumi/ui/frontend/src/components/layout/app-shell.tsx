import { Outlet } from "react-router-dom"
import { NavRail } from "./nav-rail"
import { CommandPalette } from "@/components/command-palette"

export function AppShell() {
  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background text-foreground">
      <NavRail />
      <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <Outlet />
      </main>
      <CommandPalette />
    </div>
  )
}
