import { NavLink } from "react-router-dom"
import {
  Activity,
  BarChart3,
  Clock,
  MessagesSquare,
  Moon,
  Search,
  Settings,
  Stethoscope,
  Sun,
  Wrench,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { Button } from "@/components/ui/button"
import { SimpleTooltip } from "@/components/ui/tooltip"
import { useTheme } from "@/hooks/use-theme"
import { useApp } from "@/store/app"
import { useHealth } from "@/hooks/queries"

const NAV = [
  { to: "/", label: "Chat", icon: MessagesSquare, end: true },
  { to: "/tools", label: "Tools", icon: Wrench },
  { to: "/stats", label: "Stats", icon: BarChart3 },
  { to: "/debug", label: "Debug", icon: Stethoscope },
  { to: "/timers", label: "Schedules", icon: Clock },
  { to: "/memory", label: "Memory", icon: Search },
  { to: "/settings", label: "Settings", icon: Settings },
]

function BrandMark() {
  return (
    <div className="flex size-9 items-center justify-center rounded-xl bg-gradient-to-br from-primary to-[#6d4aff] text-white shadow-lg shadow-primary/20">
      <svg viewBox="0 0 32 32" className="size-5" fill="none">
        <path
          d="M9 8.5l7 8 7-8M16 16.5V24"
          stroke="currentColor"
          strokeWidth="2.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  )
}

export function NavRail() {
  const { theme, toggle } = useTheme()
  const setCommandOpen = useApp((s) => s.setCommandOpen)
  const health = useHealth()
  const online = health.isSuccess

  return (
    <nav className="flex w-[68px] shrink-0 flex-col items-center gap-1 border-r border-sidebar-border bg-sidebar py-4">
      <div className="mb-2">
        <BrandMark />
      </div>

      {NAV.map(({ to, label, icon: Icon, end }) => (
        <SimpleTooltip key={to} label={label} side="right">
          <NavLink to={to} end={end} className="block">
            {({ isActive }) => (
              <span
                className={cn(
                  "relative flex size-11 items-center justify-center rounded-xl text-muted-foreground transition-colors",
                  "hover:bg-sidebar-accent hover:text-foreground",
                  isActive && "bg-sidebar-accent text-primary",
                )}
              >
                {isActive && (
                  <span className="absolute -left-2 h-5 w-1 rounded-full bg-primary" aria-hidden />
                )}
                <Icon className="size-[18px]" />
              </span>
            )}
          </NavLink>
        </SimpleTooltip>
      ))}

      <div className="mt-auto flex flex-col items-center gap-1">
        <SimpleTooltip label="Search & commands (⌘K)" side="right">
          <Button variant="ghost" size="icon" className="size-11 rounded-xl" onClick={() => setCommandOpen(true)}>
            <Search className="size-[18px]" />
          </Button>
        </SimpleTooltip>
        <SimpleTooltip label={theme === "dark" ? "Light mode" : "Dark mode"} side="right">
          <Button variant="ghost" size="icon" className="size-11 rounded-xl" onClick={toggle}>
            {theme === "dark" ? <Sun className="size-[18px]" /> : <Moon className="size-[18px]" />}
          </Button>
        </SimpleTooltip>
        <SimpleTooltip label={online ? "Server connected" : "Server unreachable"} side="right">
          <span className="flex size-11 items-center justify-center">
            <span className="relative flex size-2.5">
              {online && (
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-success/60" />
              )}
              <span
                className={cn(
                  "relative inline-flex size-2.5 rounded-full",
                  online ? "bg-success" : "bg-destructive",
                )}
              />
            </span>
          </span>
        </SimpleTooltip>
        <div className="flex size-9 items-center justify-center text-muted-foreground">
          <Activity className="size-4 opacity-40" />
        </div>
      </div>
    </nav>
  )
}
